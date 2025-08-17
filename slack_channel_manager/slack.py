import functools
import re
import time
from urllib.parse import urlparse

import click
import requests
from selenium import webdriver


################################################################################
# Helpers
################################################################################
@functools.lru_cache()
def get_slack_tokens(subdomain: str, d_cookie: str) -> tuple[str, str]:
    """
    Get session token and enterprise session tokenbased on the d cookie.
    https://papermtn.co.uk/retrieving-and-using-slack-cookies-for-authentication
    """
    response = requests.get(
        f"https://{subdomain}.slack.com",
        cookies={"d": d_cookie},
    )
    response.raise_for_status()

    match = re.search(r'"api_token":"([^"]+)"', response.text)
    if not match:
        raise ValueError("No api_token found in response")

    api_token = match.group(1)

    match = re.search(r'"enterprise_api_token":"([^"]+)"', response.text)
    if not match:
        raise ValueError("No enterprise_api_token found in response")

    enterprise_api_token = match.group(1)

    return api_token, enterprise_api_token


def fetch_d_cookie(subdomain: str) -> str:
    driver = webdriver.Chrome()
    driver.get(f"https://{subdomain}.slack.com")

    while urlparse(driver.current_url).netloc != "app.slack.com":
        time.sleep(0.1)

    cookies = driver.get_cookies()
    d_cookie = next(
        cookie["value"]
        for cookie in cookies
        if cookie["domain"] == ".slack.com" and cookie["name"] == "d"
    )
    driver.quit()

    return d_cookie


################################################################################
# Slack API Client
################################################################################
def _slack_raise_for_status(response: requests.Response):
    response.raise_for_status()
    if not response.json()["ok"]:
        click.secho(f"Request path: {response.request.path_url}", fg="yellow", err=True)
        click.secho(f"Request body: {response.request.body}", fg="yellow", err=True)
        click.secho(f"Response body: {response.text}", fg="red", err=True)

        raise Exception("non-OK slack response")


class SlackRequestClient:
    def __init__(self, subdomain: str, token: str, enterprise_token: str, cookie: str):
        self.enterprise_token = enterprise_token
        self.subdomain = subdomain

        self.session = requests.session()
        self.session.cookies["d"] = cookie
        self.session.headers["Authorization"] = f"Bearer {token}"

    def _make_slack_request(
        self, method: str, path: str, **kwargs
    ) -> requests.Response:
        assert path and path[0] == "/"
        url = f"https://{self.subdomain}.slack.com{path}"

        while True:
            response = self.session.request(method, url, **kwargs)
            try:
                _slack_raise_for_status(response)
                return response
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    retry_after = int(e.response.headers.get("Retry-After", 1))
                    click.secho(
                        f"Rate limit hit. Retrying after {retry_after} seconds...",
                        fg="yellow",
                    )
                    time.sleep(retry_after)
                else:
                    raise

    def get(self, path: str, **kwargs) -> dict:
        return self._make_slack_request("GET", path, **kwargs).json()

    def paginated_get(self, path: str, **kwargs) -> dict:
        assert path and "?" in path

        response = self._make_slack_request("GET", path, **kwargs)

        while cursor := response.json().get("response_metadata", {}).get("next_cursor"):
            yield response.json()

            response = self._make_slack_request(
                "GET", f"{path}&cursor={cursor}", **kwargs
            )

        return response.json()

    def post(self, path: str, data: list[tuple], **kwargs) -> dict:
        data.append(("token", self.enterprise_token))
        return self._make_slack_request("POST", path, data=data, **kwargs).json()
