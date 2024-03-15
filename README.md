# slack-channel-manager

```sh
# First, clone the repo. Then...

# Setup your environment
brew install chromedriver --cask
poetry install

# Configure the tool
poetry run manager configure # follow the prompts
poetry run manager hey # should greet you by name

# Sort!
poetry run manager sort
```

This tool relies on several Slack APIs which do not appear in the slack API
documentation. It may break at any time.

No guarantee of CLI-command level stability is offered between various commits
to this tool.

> [!Note]
> **Known issues** that have been reported:
> - _Slack client refresh:_ some users report that running the manager causes
>   their desktop slack client to fully reload. This may be related to
>   user-level themes.

## ⚠️ avoid Slack account takeovers

When you configure this tool, it fetches a potentially long-lived slack session
cookie and stores it in a file in this directory called `secret_config.json`.
Anyone with access to that cookie may interact with Slack on your behalf.

If you lose control of the file containing that cookie, or if someone else gains
access to it, [sign out of all Slack sessions](https://slack.com/help/articles/214613347-Sign-out-of-Slack)
immediately.

## set up `cron`

This tool can be run in a cron to auto-sort your channels every few minutes.
**Before setting up a cron, ensure the script is configured (above) and run it
at least once locally.** To test your setup, run:

```sh
bin/run-in-poetry.sh
```

...if you see a successful output, you may proceed.

To configure the cron, edit your crontab file (`crontab -e`) to include an entry
like:

```txt
*/5 * * * * <absolute-path-to-this-repo>/bin/run-in-poetry.sh >>~/cron-stdout.log 2>>~/cron-stderr.log
```
