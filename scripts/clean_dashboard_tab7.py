"""
Single dashboard updater entrypoint.

As requested, bots should use only this file for sheet updates.
"""

from update_live_dashboard import update_sheet as _update_sheet


def update_sheet(sheet_id='16LwZRHN0TgXOdut-RwWY805YnKsI2I8xm4AkSG2vRrU'):
    return _update_sheet(sheet_id=sheet_id)


def main():
    return update_sheet()


if __name__ == '__main__':
    main()
