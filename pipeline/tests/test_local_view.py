"""local_view.py: the page holds its modules and data, and is never written into the repository."""
import json
import os
import re

import pytest

import local_view as L

SITE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_modules_are_collected_with_renamed_imports():
    found = L.modules(os.path.join(SITE, "js"))
    assert {"trajectory/local.js", "trajectory/view.js", "trajectory/model.js", "charts/_spot.js", "util.js", "card.js"} <= set(found)
    assert not any(re.search(r'from\s+"\.', s) for s in found.values())


def test_page_cannot_be_broken_by_post_text():
    data = {"meta": {"title": "t", "subtitle": "s", "alpha": 0.9}, "users": [], "posts": {"a": {"text": "</script><b>x"}}}
    page = L.build_page(data, SITE)
    block = page.split('id="data">')[1].split("</script>")[0]
    assert json.loads(block)["posts"]["a"]["text"] == "</script><b>x"
    assert '<script type="importmap">' in page


def test_flag_reads_text_booleans():
    assert [L.flag(x) for x in (True, "t", "True", False, "f", None, float("nan"))] == [True, True, True, False, False, False, False]


def test_output_inside_the_repository_is_refused(tmp_path, monkeypatch):
    import config as cfgmod
    from tests.test_aggregate import make_cfg
    cfg = make_cfg(tmp_path)
    inv = tmp_path / "inv.parquet"
    inv.write_bytes(b"x")
    monkeypatch.setattr(cfgmod, "load", lambda here: cfg)
    with pytest.raises(SystemExit):
        L.main(["--tables", str(tmp_path), "--inventory", str(inv), "--out", os.path.join(cfg.site_dir, "x.html")])


def test_preview_serves_every_module_of_the_page():
    import preview
    for name in L.modules(os.path.join(SITE, "js")):
        h = preview.Handler.__new__(preview.Handler)
        h.site_dir, h.data_dir = SITE, SITE
        assert h.translate_path("/js/" + name) == os.path.join(SITE, "js/" + name), name
