import unittest

from crawler import extract_article_text

BODY = ("<p>Anthropic presentó este martes un paquete de novedades que convierte "
        "a Claude en una suite ofimática con IA, con hojas de cálculo, pizarras y "
        "cuadros de mando dentro del propio chat para equipos de empresa.</p>")


class PageFurnitureTest(unittest.TestCase):
    def test_prev_next_post_headlines_are_dropped(self):
        # Zox News WordPress theme (MuyComputerPro): the next post's headline
        # sits in <p> under the article.
        html = f"""<html><body><article><div class="entry">{BODY}
          <div id="mvp-prev-next-wrap"><div class="mvp-prev-post-wrap"><a href="#">
            <div class="mvp-prev-next-text"><p>Google presenta TPU 8tx, un acelerador
            de IA con computación confidencial por hardware</p></div></a></div></div>
          </div></article></body></html>"""
        text = extract_article_text(html)
        self.assertIn("suite ofimática", text)
        self.assertNotIn("confidencial", text)

    def test_more_posts_list_is_dropped(self):
        html = f"""<html><body><article>{BODY}
          <div id="mvp-post-more-wrap"><ul class="mvp-post-more-list"><li><a href="#">
            <div class="mvp-post-more-text"><p>Confidential computing comes to TPUs</p>
            </div></a></li></ul></div></article></body></html>"""
        text = extract_article_text(html)
        self.assertNotIn("Confidential", text)


if __name__ == "__main__":
    unittest.main()
