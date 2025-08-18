import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

import click


@dataclass
class ChannelSectionConfig:
    section_name: str
    section_emoji: str
    channel_regex: str
    compiled_regex: re.Pattern = field(init=False)
    _section_id: str = field(init=False, default=None)
    
    def __post_init__(self):
        self.compiled_regex = re.compile(self.channel_regex)
    
    @property
    def section_id(self) -> str:
        if self._section_id is None:
            raise ValueError("section_id has not been set")
        return self._section_id
    
    @section_id.setter
    def section_id(self, value: str) -> None:
        self._section_id = value


class ConfigKey(Enum):
    SUBDOMAIN = "slack_subdomain"
    SECTIONS = "slack_channel_sections"
    D_COOKIE = "slack_d_cookie"


class ConfigManager:
    def __init__(self, filename: str = "secret_config.json") -> None:
        self.file_path: Path = Path(filename)
        self.data: dict[str, any] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load data from the JSON config file."""
        if self.file_path.exists():
            with self.file_path.open("r") as file:
                try:
                    self.data = json.load(file)
                except json.JSONDecodeError:
                    raise ValueError(
                        f"The config file {self.file_path} contains invalid JSON."
                    )

    def _save_config(self) -> None:
        """Save data to the JSON config file."""
        with self.file_path.open("w") as file:
            json.dump(self.data, file, indent=4)

    def is_configured(self) -> bool:
        """Check if the config file has all the required keys."""
        if not all(key.value in self.data for key in ConfigKey):
            return False

        # Check that sections list exists and has at least one valid section
        sections = self.data.get(ConfigKey.SECTIONS.value, [])
        if len(sections) < 1:
            return False

        # Validate each section can be parsed as ChannelSectionConfig
        try:
            for section_data in sections:
                ChannelSectionConfig(**section_data)
        except (TypeError, ValueError):
            return False

        return True

    def get(self, key: ConfigKey, default: any = None, required: bool = True) -> any:
        """Retrieve a value from the config. Differs from standard gets in that it errors on missing values by default."""
        value = self.data.get(key.value, default)
        if required and not value:
            raise ValueError(f"Missing required configuration key: {key}")

        return value

    def upsert(self, key: ConfigKey, value: any) -> None:
        """Update or insert a value in the config and save."""
        if key in ConfigKey:
            self.data[key.value] = value
            self._save_config()
        else:
            raise ValueError(f"Invalid configuration key: {key}")

    def delete(self, key: ConfigKey) -> None:
        """Delete a key from the config and save."""
        if key.value in self.data:
            del self.data[key.value]
            self._save_config()

    def __dict__(self) -> dict[str, any]:
        return self.data


def reload_config(
    config: ConfigManager, d_cookie_fetcher: Callable[[str], str]
) -> None:
    subdomain = (
        click.prompt(
            "Slack subdomain (e.g., 'foo' in 'foo.slack.com')",
            type=str,
            default=config.get(ConfigKey.SUBDOMAIN, required=False),
            show_default=True
            if config.get(ConfigKey.SUBDOMAIN, required=False)
            else False,
        )
        .strip()
        .lower()
    )
    if "." in subdomain or "/" in subdomain:
        raise ValueError("Invalid subdomain")
    config.upsert(ConfigKey.SUBDOMAIN, subdomain)

    # Load and validate existing sections
    existing_sections_data = (
        config.get(ConfigKey.SECTIONS, default=[], required=False) or []
    )
    valid_sections = []

    for section_data in existing_sections_data:
        try:
            valid_sections.append(ChannelSectionConfig(**section_data))
        except (TypeError, ValueError) as e:
            click.secho(
                f"Removing corrupt section: {section_data} (error: {e})", fg="red"
            )

    # Show existing valid sections
    if valid_sections:
        click.echo("\nExisting sections:")
        for i, section in enumerate(valid_sections, 1):
            click.echo(
                f"  {i}. {section.section_name} :{section.section_emoji}: (regex: {section.channel_regex})"
            )
        click.secho(f"To remove sections, edit {config.file_path}", fg="red")

    if click.confirm("Do you want to configure a new section?"):
        new_sections = []
        while True:
            click.echo(f"\nConfiguring new section {len(new_sections) + 1}:")

            section_name = (
                click.prompt(
                    "Name of section for grouped channels (e.g., 'incidents')",
                    type=str,
                    default="incidents"
                    if len(valid_sections + new_sections) == 0
                    else None,
                    show_default=len(valid_sections + new_sections) == 0,
                )
                .strip()
                .lower()
            )
            if " " in section_name:
                raise ValueError("Invalid section name")

            section_emoji = (
                click.prompt(
                    "Emoji for section for grouped channels (e.g., 'fire' for :fire:)",
                    type=str,
                    default="fire" if len(valid_sections + new_sections) == 0 else None,
                    show_default=len(valid_sections + new_sections) == 0,
                )
                .strip()
                .lower()
            )
            if " " in section_emoji:
                raise ValueError("Invalid section emoji")

            channel_regex = click.prompt(
                "Regex for channels to sort (e.g., '^inc-', can be partial match)",
                type=str,
                default="^inc-" if len(valid_sections + new_sections) == 0 else None,
                show_default=len(valid_sections + new_sections) == 0,
            )
            try:
                re.compile(channel_regex)
            except re.error:
                raise ValueError("Invalid regex")

            new_sections.append(
                ChannelSectionConfig(
                    section_name=section_name,
                    section_emoji=section_emoji,
                    channel_regex=channel_regex,
                )
            )

            if not click.confirm("Do you want to configure another section?"):
                break

        # Combine existing and new sections
        all_sections = valid_sections + new_sections
        config.upsert(
            ConfigKey.SECTIONS,
            [
                {
                    "section_name": section.section_name,
                    "section_emoji": section.section_emoji,
                    "channel_regex": section.channel_regex,
                }
                for section in all_sections
            ],
        )

    if not config.get(ConfigKey.D_COOKIE, required=False) or click.confirm(
        "Re-authenticate to Slack?"
    ):
        click.echo(
            "Next we'll open a browser window. Log in to slack, and this script will capture your session cookie."
        )
        click.confirm("Enter y to continue...", abort=True)
        config.upsert(
            ConfigKey.D_COOKIE, d_cookie_fetcher(config.get(ConfigKey.SUBDOMAIN))
        )

    click.echo("Configuration saved!\n")
