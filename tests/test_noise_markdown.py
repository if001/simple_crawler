from search_scrape.extractor import SimpleHtmlCleaner


def test_noise_removed_and_links_unwrapped():
    html = """
    <html><head><title>T</title></head>
    <body>
      <nav>menu</nav>
      <main>
        <p>hello <a href="https://x">link</a></p>
        <img src="x.png"/>
      </main>
      <footer>footer</footer>
    </body></html>
    """
    title, cleaned = SimpleHtmlCleaner().clean(html)
    assert title == "T"
    assert "menu" not in cleaned
    assert "footer" not in cleaned
    assert "href" not in cleaned  # unwrap済み
    assert "img" not in cleaned
