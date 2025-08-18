#!/usr/bin python

import functools
import json
from typing import Any

import click

from slack_channel_manager.config import (
    ChannelSectionConfig,
    ConfigKey,
    ConfigManager,
    reload_config,
)
from slack_channel_manager.slack import (
    SlackRequestClient,
    fetch_d_cookie,
    get_slack_tokens,
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
    token, enterprise_token = get_slack_tokens(
        subdomain=CONFIG.get(ConfigKey.SUBDOMAIN),
        d_cookie=CONFIG.get(ConfigKey.D_COOKIE),
    )
    return SlackRequestClient(
        subdomain=CONFIG.get(ConfigKey.SUBDOMAIN),
        token=token,
        enterprise_token=enterprise_token,
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

    # Ensure the sections exist (and get their IDs)
    # This API is undocumented. It appears to be paginated, but the mechanics
    # are unclear, and most users will have only one page of sections anyway.
    slack_sections = client.get("/api/users.channelSections.list")["channel_sections"]

    channel_id_to_section_id: dict[str, str] = {}
    section_name_to_section: dict[str, dict[str, Any]] = {}
    for section in slack_sections:
        section_name_to_section[section["name"].lower().strip()] = section
        for channel_id in section["channel_ids_page"].get("channel_ids", []):
            channel_id_to_section_id[channel_id] = section["channel_section_id"]

    # Get configured sections and ensure they exist
    sections = [
        ChannelSectionConfig(**section_data)
        for section_data in CONFIG.get(ConfigKey.SECTIONS)
    ]
    for section_config in sections:
        channel_section_id = section_name_to_section.get(
            section_config.section_name.lower().strip(), {}
        ).get("channel_section_id")

        # Create the section if it doesn't exist
        if not channel_section_id:
            channel_section_id = client.post(
                "/api/users.channelSections.create",
                data=[
                    ("name", section_config.section_name),
                    ("emoji", section_config.section_emoji),
                ],
            )["channel_section_id"]
            click.secho(
                f"Created '{section_config.section_name}' section: {channel_section_id}",
                fg="green",
            )
            click.secho(
                "Slack defaults new sections to the very bottom of your sidebar, below DMs, bots, etc. Reposition it as desired in the Slack client.",
                fg="yellow",
            )

        section_config.section_id = channel_section_id

    # Page through all available channels once
    total_channels_moved = 0
    for page in client.paginated_get(
        "/api/conversations.list?exclude_archived=true&types=public_channel&limit=1000"
    ):
        # Group channels by target section
        section_channels = {section.section_id: [] for section in sections}

        for channel in page["channels"]:
            if not channel["is_member"] or channel_id_to_section_id.get(channel["id"]):
                continue

            for section_config in sections:
                if section_config.compiled_regex.match(channel["name"]):
                    section_channels[section_config.section_id].append(channel)
                    break

        # Bulk update each section that has channels to move
        for section_config in sections:
            channels_to_move = section_channels[section_config.section_id]
            if not channels_to_move:
                continue

            click.echo(
                f"Moving channels to '{section_config.section_name}' section: {[channel['name'] for channel in channels_to_move]}"
            )
            client.post(
                "/api/users.channelSections.channels.bulkUpdate",
                data=[
                    (
                        "insert",
                        json.dumps(
                            [
                                {
                                    "channel_section_id": section_config.section_id,
                                    "channel_ids": [
                                        channel["id"] for channel in channels_to_move
                                    ],
                                }
                            ]
                        ),
                    )
                ],
            )
            total_channels_moved += len(channels_to_move)

    click.secho(
        f"Moved {total_channels_moved} channels across all sections",
        fg="green",
    )


if __name__ == "__main__":
    cli()
