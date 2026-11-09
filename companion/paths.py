from pathlib import Path


def project_dir():
    """The project folder (where app.py lives): the page in static/ is read from here."""
    return Path(__file__).resolve().parent.parent


def user_dir():
    """Files the user edits or that grow over time: persona.md, clips/, fillers/, data/.
    The project folder."""
    return project_dir()
