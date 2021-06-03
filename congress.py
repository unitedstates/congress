import click

from tasks import bills, votes


@click.group()
def cli():
    """
    Command-line interface for the congress library.
    """


@cli.command()
@click.option("--bill_id", required=True, help="ID of the bill.")
@click.option("--custom_fetch_function", default=None)
def get_bill(bill_id, custom_fetch_function):
    """Get bill by ID."""
    bills.run({"bill_id": bill_id, "reparse_actions": custom_fetch_function})


@cli.command()
@click.option("--limit", default=None, help="Limit number of votes returned.")
@click.option("--custom_fetch_function", default=None)
def get_bills(limit, custom_fetch_function):
    """Get votes."""
    bills.run({"limit": limit, "reparse_actions": custom_fetch_function})


@cli.command()
@click.option("--vote_id", required=True, help="ID of the vote.")
def get_vote(vote_id):
    """Get vote by ID."""
    votes.run({"vote_id": vote_id})


@cli.command()
@click.option(
    "--session",
    default=None,
    help="Filters votes based on congressional session (ex. 116, 117).",
)
@click.option(
    "--chamber",
    default=None,
    help="Filters votes based on congressional chamber.",
    type=click.Choice(["House", "Senate"], case_sensitive=False),
)
@click.option("--limit", default=None, help="Limit number of votes returned.")
def get_votes(session, chamber, limit):
    """Get votes."""
    votes.run(
        {
            "limit": limit,
            "chamber": chamber,
            "congress": True if session is not None else False,
            "session": session,
        }
    )


if __name__ == "__main__":
    cli()
