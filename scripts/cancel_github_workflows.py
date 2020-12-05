#!/usr/bin/env python3
"""
Manually GitHub workflow runs
"""
import os
from dateutil import parser
from typing import Iterable, List, Optional, Union

import click
import requests
from click.exceptions import ClickException
from typing_extensions import Literal

github_token = os.environ.get("GITHUB_TOKEN")


def request(method: Literal["GET", "POST", "DELETE", "PUT"], endpoint: str, **kwargs):
    resp = requests.request(
        method,
        f"https://api.github.com/{endpoint.lstrip('/')}",
        headers={"Authorization": f"Bearer {github_token}"},
        **kwargs,
    ).json()
    if "message" in resp:
        raise ClickException(f"{method} {endpoint} >> {resp['message']} <<")
    return resp


def list_runs(repo: str, params=None):
    return request("GET", f"/repos/{repo}/actions/runs", params=params)


def cancel_run(repo: str, run_id: Union[str, int]):
    return request("POST", f"/repos/{repo}/actions/runs/{run_id}/cancel")


def get_pull_request(repo: str, pull_number: Union[str, int]):
    return request("GET", f"/repos/{repo}/pulls/{pull_number}")


def get_runs_by_branch(
    repo: str,
    branch: str,
    user: Optional[str] = None,
    statuses: Iterable[str] = ("queued", "in_progress"),
    events: Iterable[str] = ("pull_request", "push"),
):
    """Get workflow runs associated with the given branch"""
    return [
        item
        for event in events
        for status in statuses
        for item in list_runs(repo, {"event": event, "status": status})["workflow_runs"]
        if item["head_branch"] == branch
        and (user is None or (user == item["head_repository"]["owner"]["login"]))
    ]


def print_commit(commit):
    """Print out commit message for verification"""
    indented_message = "    \n".join(commit["message"].split("\n"))
    print(
        f"""
HEAD {commit["id"]}
Author: {commit["author"]["name"]} <{commit["author"]["email"]}>
Date:   {parser.parse(commit["timestamp"]).astimezone(tz=None).strftime("%a, %d %b %Y %H:%M:%S")}

    {indented_message}
"""
    )


@click.command()
@click.option(
    "--repo",
    default="apache/incubator-superset",
    help="Default is apache/incubator-superset",
)
@click.option(
    "--event",
    type=click.Choice(["pull_request", "push", "issue"]),
    default=["pull_request", "push"],
    multiple=True,
    help="One of more pull_request, push or issue",
)
@click.option(
    "--keep-last/--no-keep-last", default=True, help="Don't cancel the lastest runs"
)
@click.option(
    "--keep-running/--no-keep-running",
    default=True,
    help="Whether to skip cancelling running workflows",
)
@click.argument("branch_or_pull")
def cancel_github_workflows(
    branch_or_pull: str, repo, event: List[str], keep_last: bool, keep_running: bool
):
    """Cancel running or queued GitHub workflows by branch or pull request ID."""
    if not github_token:
        raise ClickException("Please provide GITHUB_TOKEN as an env variable")

    statuses = ("queued",) if keep_running else ("queued", "in_progress")
    pr = None

    if branch_or_pull.isdigit():
        pr = get_pull_request(repo, pull_number=branch_or_pull)
        target_type = "pull request"
        title = f"#{pr['number']} - {pr['title']}"
    else:
        target_type = "branch"
        title = branch_or_pull

    print(f"\nCancelling workflow runs for {target_type}\n\n    {title}\n")

    if pr:
        # full branch name
        runs = get_runs_by_branch(
            repo,
            statuses=statuses,
            events=event,
            branch=pr["head"]["ref"],
            user=pr["user"]["login"],
        )
    else:
        user = None
        branch = branch_or_pull
        if ":" in branch:
            [user, branch] = branch.split(":", 2)
        runs = get_runs_by_branch(
            repo, statuses=statuses, events=event, branch=branch_or_pull, user=user
        )

    runs = sorted(runs, key=lambda x: x["created_at"])
    if not runs:
        print(f"No {' or '.join(statuses)} workflow runs found.\n")
        return

    last_sha = runs[-1]["head_commit"]["id"]
    if keep_last:
        # Find the head commit SHA of the last created workflow run
        runs = [x for x in runs if x["head_commit"]["id"] != last_sha]
        if not runs:
            print(
                "Only the latest runs are in queue. Use --no-keep-last to force cancelling them.\n"
            )
            return

    last_sha = None

    for entry in runs:
        head_commit = entry["head_commit"]
        if head_commit["id"] != last_sha:
            last_sha = head_commit["id"]
            print_commit(head_commit)
        try:
            cancel_run(repo, entry["id"])
            print(f"[Cancled] {entry['name']}")
        except ClickException as error:
            print(f"[Cancled] {entry['name']} [Error: {error.message}]")
    print("")


if __name__ == "__main__":
    # pylint: disable=no-value-for-parameter
    cancel_github_workflows()
