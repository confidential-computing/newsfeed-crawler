import io
import unittest

from crawler import _outlet_name, _story_lead, _write_webfeed_grouped

GN = "https://news.google.com/rss/articles/"


def art(title, url, lang="en", cluster=0, published="Mon, 09 Nov 2026 12:00:00 UTC",
        publisher="Google News CC", **extra):
    return dict(title=title, url=url, lang=lang, _cluster=cluster,
                published=published, publisher=publisher, **extra)


def render(articles, labels={0: "story", 1: "other"}):
    f = io.StringIO()
    _write_webfeed_grouped(f, articles, labels, lambda a: f"(P: {a['publisher']})")
    return f.getvalue().splitlines()


class GroupedWebfeedTest(unittest.TestCase):
    def test_story_folds_coverage_by_language(self):
        lines = render([
            art("AMD EPYC to power TPU 8tx - SMBtech", GN + "1"),
            art("Google TPU 8tx pairs EPYC", "https://www.servethehome.com/x",
                publisher="ServeTheHome", published="Mon, 09 Nov 2026 21:00:00 UTC"),
            art("AMD EPYC for TPU 8tx - 디일렉", "https://www.thelec.kr/1", lang="ko",
                publisher="디일렉", title_original="AMD 에픽 TPU 8tx"),
            art("Google presents TPU 8tx", "https://www.muycomputerpro.com/1", lang="es",
                publisher="MuyComputerPro", title_original="Google presenta TPU 8tx"),
            art("A separate story", "https://example.com/s", cluster=1, publisher="Example"),
        ])
        self.assertEqual(len([l for l in lines if l.startswith("- ")]), 2)
        # Direct English link leads, though the Google News copy is earlier
        self.assertTrue(lines[0].startswith("- [Google TPU 8tx pairs EPYC]"))
        self.assertEqual(lines[1], f"  - More in English (1): [SMBtech]({GN}1)")
        self.assertIn("  - Also in Korean | 한국어로도 (1): [디일렉](https://www.thelec.kr/1)", lines)
        self.assertIn("  - Also in Spanish | También en español (1): "
                      "[MuyComputerPro](https://www.muycomputerpro.com/1)", lines)
        self.assertTrue(lines[-1].startswith("- [A separate story]"))

    def test_bigger_stories_first_singletons_keep_order(self):
        lines = render([
            art("First single", "https://a.example/1", cluster=5, publisher="A"),
            art("Big one", "https://b.example/1", cluster=1, publisher="B"),
            art("Big two", "https://c.example/1", cluster=1, publisher="C"),
            art("Second single", "https://d.example/1", cluster=6, publisher="D"),
        ], labels={1: "big", 5: "x", 6: "y"})
        tops = [l for l in lines if l.startswith("- ")]
        self.assertEqual([t.split("]")[0] for t in tops],
                         ["- [Big one", "- [First single", "- [Second single"])

    def test_no_clusters_means_one_bullet_each(self):
        lines = render([art("One", "https://a.example/1"), art("Two", "https://b.example/1")],
                       labels={})
        self.assertEqual(lines, ["- [One](https://a.example/1) (P: Google News CC)",
                                 "- [Two](https://b.example/1) (P: Google News CC)"])

    def test_non_english_story_leads_with_its_own_article(self):
        lead = _story_lead([art("Japan market", GN + "9", lang="ja")])
        self.assertEqual(lead["lang"], "ja")


class OutletNameTest(unittest.TestCase):
    def test_google_news_outlet_from_headline(self):
        self.assertEqual(_outlet_name(art("Chips power AI - Investing.com - FX | 株式市場 | 金融ニュース",
                                          GN + "1", lang="ja")), "Investing.com")
        self.assertEqual(_outlet_name(art("TPU news - https://fomoera.com/", GN + "2")),
                         "fomoera.com")

    def test_english_outlet_with_non_latin_brand(self):
        self.assertEqual(_outlet_name(art("Google launches TPUs - 富途牛牛", GN + "3",
                                          publisher="富途牛牛")), "Futu (富途牛牛)")

    def test_direct_link_uses_publisher(self):
        self.assertEqual(_outlet_name(art("x", "https://www.thelec.kr/1", publisher="디일렉")),
                         "디일렉")


if __name__ == "__main__":
    unittest.main()
