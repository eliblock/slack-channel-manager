#!/usr/bin python

import functools
import json
import re
import time

import click

from slack_channel_manager.config import ConfigKey, ConfigManager, reload_config
from slack_channel_manager.slack import (
    SlackRequestClient,
    fetch_d_cookie,
    get_slack_token,
)

################################################################################
# Configuration
################################################################################
CONFIG = ConfigManager()


################################################################################
# Helpers
################################################################################
@functools.lru_cache()
def get_slack_client() -> "SlackRequestClient":
    return SlackRequestClient(
        subdomain=CONFIG.get(ConfigKey.SUBDOMAIN),
        token=get_slack_token(
            subdomain=CONFIG.get(ConfigKey.SUBDOMAIN),
            d_cookie=CONFIG.get(ConfigKey.D_COOKIE),
        ),
        cookie=CONFIG.get(ConfigKey.D_COOKIE),
    )


def ensure_configured(cmd):
    @functools.wraps(cmd)
    def wrapper(*args, **kwargs):
        ctx = click.get_current_context()
        if not CONFIG.is_configured():
            click.echo("Configuration not found. Attempting to re-configure...")
            reload_config(config=CONFIG, d_cookie_fetcher=fetch_d_cookie)
        return ctx.invoke(cmd, *args, **kwargs)

    return wrapper


################################################################################
# CLI
################################################################################
@click.group()
def cli():
    pass


@cli.command()
def configure():
    reload_config(config=CONFIG, d_cookie_fetcher=fetch_d_cookie)


@cli.command()
@ensure_configured
def hey():
    profile = get_slack_client().get("/api/users.profile.get")
    click.echo(
        f"Hello {profile['profile']['display_name_normalized']} ({profile['profile']['email']})"
    )


@cli.command()
@ensure_configured
def sort():
    client = get_slack_client()

    # Ensure the section exists (and get its ID)
    # This API is undocumented. It appears to be paginated, but the mechanics
    # are unclear, and most users will have only one page of sections anyway.
    sections = client.get("/api/users.channelSections.list")["channel_sections"]
    channel_id_to_section_id: dict[str, str] = {}
    channel_section_id: str | None = None
    desired_section_name = CONFIG.get(ConfigKey.SECTION_NAME)
    for section in sections:
        if section["name"].lower() == desired_section_name.lower():
            channel_section_id = section["channel_section_id"]

            for channel_id in section["channel_ids_page"].get("channel_ids", []):
                # It is unclear how to fetch _additional_ pages of channel_ids,
                # but the first page should be sufficient for most users.
                channel_id_to_section_id[channel_id] = channel_section_id

    if not channel_section_id:
        # Create the section
        # This API is undocumented.
        channel_section_id = client.post(
            "/api/users.channelSections.create",
            data=[
                ("name", desired_section_name),
                ("emoji", CONFIG.get(ConfigKey.SECTION_EMOJI)),
            ],
        )["channel_section_id"]
        click.echo(f"Created '{desired_section_name}' section: {channel_section_id}")
        click.echo(
            "Slack defaults new sections to the very bottom of your sidebar. Reposition it as desired in the Slack client."
        )

    channel_regex = re.compile(CONFIG.get(ConfigKey.CHANNEL_REGEX))

    # Page through all available channels, moving any which meet the following
    # criteria to the target section:
    # * they are not already in a section
    # * you are in them
    # * they match the target regex
    channels_moved: int = 0
    for page in client.paginated_get(
        "/api/conversations.list?exclude_archived=true&types=public_channel&limit=1000"
    ):
        page_target_channels = [
            channel
            for channel in page["channels"]
            if channel["is_member"]
            and not channel_id_to_section_id.get(channel["id"])
            and channel_regex.match(channel["name"])
        ]

        if not page_target_channels:
            time.sleep(0.25)  # slack has rate limits, let's naively wait a bit
            continue

        # Add the channels to the section
        # This API is undocumented.
        click.echo(
            f"Moving channels to '{desired_section_name}' section: {[channel['name'] for channel in page_target_channels]}"
        )
        client.post(
            "/api/users.channelSections.channels.bulkUpdate",
            data=[
                (
                    "insert",
                    json.dumps(
                        [
                            {
                                "channel_section_id": channel_section_id,
                                "channel_ids": [
                                    channel["id"] for channel in page_target_channels
                                ],
                            }
                        ]
                    ),
                )
            ],
        )
        channels_moved += len(page_target_channels)

        time.sleep(0.25)  # slack has rate limits, let's naively wait a bit

    click.echo(
        f"Moved {channels_moved} channels to '{desired_section_name}' section (some may have already been assigned)"
    )


if __name__ == "__main__":
    cli()
