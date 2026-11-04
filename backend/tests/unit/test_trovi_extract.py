"""Archive containment for Trovi downloads (same rules as marketplace artifacts)."""
import io
import os
import tarfile

import pytest

from app.routes.trovi import _extract_archive


def _tar(path, members):
    with tarfile.open(path, "w:gz") as tf:
        for info, data in members:
            tf.addfile(info, io.BytesIO(data) if data is not None else None)


def _file(name, data=b"x"):
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    return info, data


def test_plain_archive_extracts_and_strips_top_dir(tmp_path):
    archive = tmp_path / "a.tgz"
    _tar(archive, [_file("pkg/README.md"), _file("pkg/run.sh")])
    dest = tmp_path / "dest"
    dest.mkdir()

    assert _extract_archive(str(archive), str(dest)) is True
    assert (dest / "README.md").exists() and (dest / "run.sh").exists()


@pytest.mark.parametrize("linktype", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_link_members_are_rejected(tmp_path, linktype):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tarfile.TarInfo(name="pkg/cfg")
    link.type = linktype
    link.linkname = str(outside) if linktype == tarfile.SYMTYPE else "pkg/README.md"
    archive = tmp_path / "evil.tgz"
    _tar(archive, [_file("pkg/README.md"), (link, None), _file("pkg/cfg/id_token.json", b"evil")])
    dest = tmp_path / "dest"
    dest.mkdir()

    assert _extract_archive(str(archive), str(dest)) is False
    assert not os.listdir(dest)
    assert not os.listdir(outside)


def test_traversal_member_is_rejected(tmp_path):
    archive = tmp_path / "evil.tgz"
    _tar(archive, [_file("../escape.txt")])
    dest = tmp_path / "dest"
    dest.mkdir()

    assert _extract_archive(str(archive), str(dest)) is False
    assert not (tmp_path / "escape.txt").exists()
