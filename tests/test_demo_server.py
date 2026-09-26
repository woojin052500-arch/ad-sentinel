import demo_server


def test_demo_paths_map_to_fixtures():
    handler = object.__new__(demo_server.DemoHandler)
    handler.directory = str(demo_server.SITE_DIR)
    assert handler.translate_path("/old/home.html?play=x").endswith("reflect/home.html")
    assert handler.translate_path("/index.html").endswith("site/index.html")
    assert handler.translate_path("/gate/main.html").endswith("gate/main.html")
    assert (demo_server.SITE_DIR / "index.html").is_file()
    assert (demo_server.OLD_DIR / "home.html").is_file()


def test_demo_url_list_is_readable(tmp_path, monkeypatch):
    from ad_sentinel.url_list import load_url_list

    monkeypatch.setattr(demo_server, "output_dir", lambda: tmp_path)
    path = demo_server.write_url_list("http://127.0.0.1:8000/")
    urls = load_url_list(path)
    assert len(urls) == 4 and urls[0].startswith("http://127.0.0.1:8000/old/home.html?play=")
