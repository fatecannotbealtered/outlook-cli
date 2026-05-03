"""Folder commands: list, create, rename, move, empty, delete."""

import click

from .. import output
from ..exchange import get_account


@click.group()
def folders_group():
    """Mail folder management."""
    pass


def _folder_to_dict(folder, depth=0, max_depth=3):
    """Convert folder to dict, recursively up to max_depth."""
    result = {
        "name": folder.name,
        "total_count": folder.total_count or 0,
        "unread_count": folder.unread_count or 0,
    }
    if depth < max_depth:
        children = []
        try:
            for child in folder.children:
                children.append(_folder_to_dict(child, depth + 1, max_depth))
        except Exception:
            pass
        if children:
            result["children"] = children
    return result


def _find_folder(account, path):
    """Find folder by path. Returns None if not found."""
    parts = [p.strip() for p in path.split("/") if p.strip()]
    if not parts:
        return None
    folder = account.inbox.parent
    for part in parts:
        found = None
        try:
            for child in folder.children:
                if child.name == part:
                    found = child
                    break
        except Exception:
            return None
        if found is None:
            return None
        folder = found
    return folder


@folders_group.command("list")
@click.option("--max-depth", default=3, type=int, help="Folder tree depth (default 3)")
@click.pass_context
def folders_list(ctx, max_depth):
    """List all mail folders."""
    from ..config import check_permission
    check_permission("folders list")

    account = get_account()
    try:
        folders = [_folder_to_dict(f, max_depth=max_depth) for f in account.inbox.parent.children]
    except Exception as e:
        output.handle_error(f"Failed to list folders: {e}", "SERVER_ERROR", exit_code=7)

    data = {"count": len(folders), "folders": folders}

    if output.is_json():
        output.print_json(data)
    else:
        _print_folder_tree(folders, indent=0)


def _print_folder_tree(folders, indent=0):
    """Pretty-print folder tree."""
    prefix = "  " * indent
    for f in folders:
        unread = f" ({f['unread_count']} unread)" if f["unread_count"] else ""
        total = f"[{f['total_count']}]"
        output.info(f"{prefix}{f['name']} {total}{unread}")
        if "children" in f:
            _print_folder_tree(f["children"], indent + 1)


@folders_group.command("create")
@click.option("--name", required=True, help="Folder path (e.g. 'Projects/Alpha')")
@click.pass_context
def folders_create(ctx, name):
    """Create a new mail folder."""
    from ..config import check_permission
    check_permission("folders create")

    from exchangelib import Folder
    account = get_account()
    parts = [p.strip() for p in name.split("/") if p.strip()]
    if not parts:
        output.handle_error("Folder name cannot be empty", "VALIDATION_ERROR", exit_code=2)

    parent = account.inbox.parent
    created = []
    for part in parts:
        existing = None
        try:
            for child in parent.children:
                if child.name == part:
                    existing = child
                    break
        except Exception:
            pass

        if existing:
            parent = existing
        else:
            if ctx.obj.get("dry_run"):
                output.info(f"[DRY RUN] Would create folder: {part}")
                continue
            new_folder = Folder(parent=parent, name=part)
            new_folder.save()
            created.append(part)
            parent = new_folder

    if not created:
        data = {"message": f"Folder already exists: {name}"}
    else:
        data = {"message": f"Folder created: {name}", "created": created}

    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@folders_group.command("rename")
@click.option("--name", required=True, help="Current folder path")
@click.option("--new-name", required=True, help="New folder name")
@click.pass_context
def folders_rename(ctx, name, new_name):
    """Rename a mail folder."""
    from ..config import check_permission
    check_permission("folders rename")

    account = get_account()
    folder = _find_folder(account, name)
    if not folder:
        output.handle_error(f"Folder not found: {name}", "NOT_FOUND", exit_code=4)

    old_name = folder.name
    folder.name = new_name
    folder.save(update_fields=["name"])

    data = {"message": f"Renamed: {old_name} -> {new_name}"}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@folders_group.command("move")
@click.option("--name", required=True, help="Folder path to move")
@click.option("--target", required=True, help="Destination folder path")
@click.pass_context
def folders_move(ctx, name, target):
    """Move a folder under another folder."""
    from ..config import check_permission
    check_permission("folders move")

    account = get_account()
    src = _find_folder(account, name)
    if not src:
        output.handle_error(f"Source folder not found: {name}", "NOT_FOUND", exit_code=4)

    dst = _find_folder(account, target)
    if not dst:
        output.handle_error(f"Target folder not found: {target}", "NOT_FOUND", exit_code=4)

    src.move(dst)

    data = {"message": f"Moved: {name} -> {target}/"}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@folders_group.command("empty")
@click.option("--name", required=True, help="Folder path to empty")
@click.option("--force", is_flag=True, help="Skip confirmation")
@click.pass_context
def folders_empty(ctx, name, force):
    """Empty a mail folder (moves all items to trash)."""
    from ..config import check_permission
    check_permission("folders empty")

    account = get_account()
    folder = _find_folder(account, name)
    if not folder:
        output.handle_error(f"Folder not found: {name}", "NOT_FOUND", exit_code=4)

    if not force and not output.is_json():
        click.confirm(f"Empty folder '{name}'? All items will be moved to trash.", abort=True)

    folder.empty()

    data = {"message": f"Folder emptied: {name}"}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@folders_group.command("delete")
@click.option("--name", required=True, help="Folder path to delete")
@click.option("--force", is_flag=True, help="Skip confirmation")
@click.pass_context
def folders_delete(ctx, name, force):
    """Delete a mail folder."""
    from ..config import check_permission
    check_permission("folders delete")

    account = get_account()
    folder = _find_folder(account, name)
    if not folder:
        output.handle_error(f"Folder not found: {name}", "NOT_FOUND", exit_code=4)

    if not force and not output.is_json():
        click.confirm(f"Delete folder '{name}'?", abort=True)

    folder.delete()

    data = {"message": f"Folder deleted: {name}"}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])
