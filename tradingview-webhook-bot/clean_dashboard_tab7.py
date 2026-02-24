"""
Single dashboard updater entrypoint.

As requested, bots should use only this file for sheet updates.
"""

from update_live_dashboard import update_sheet as _update_sheet


def update_sheet(sheet_id='1yLea3lhNqItSJCjMOYS2btjLjsRfKLMcfEHHSPfRKbw'):
    return _update_sheet(sheet_id=sheet_id)


def main():
    return update_sheet()


if __name__ == '__main__':
    main()
