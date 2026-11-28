import io
import random

from PIL import Image, PngImagePlugin

from mitski.social.avatar import ai_in_text, ai_markers, hours_range, rank, square


def png(w=800, h=1200, text=None):
    info = PngImagePlugin.PngInfo()
    for k, v in (text or {}).items():
        info.add_text(k, v)
    out = io.BytesIO()
    Image.new("RGB", (w, h), (200, 120, 160)).save(out, "PNG", pnginfo=info)
    return out.getvalue()


def test_the_interval_is_a_number_or_a_range():
    assert hours_range(48) == (48, 48)
    assert hours_range([24, 72]) == (24, 72)
    assert hours_range([72, 24]) == (24, 72)
    assert hours_range([0.1]) == (0.5, 0.5)


def test_ai_generation_metadata_is_caught():
    assert ai_markers(png(text={"parameters": "kayoko, Steps: 28, Sampler: Euler a, CFG scale: 7"}))
    assert ai_markers(png(text={"Software": "NovelAI"}))
    assert ai_markers(b"xmp digitalsourcetype trainedAlgorithmicMedia")
    assert ai_markers(png()) is None


def test_ai_words_in_titles_are_caught_but_not_a_character_called_ai():
    assert ai_in_text("Kayoko AI art", "onikata kayoko")
    assert ai_in_text("kayoko stable diffusion lora", "onikata kayoko")
    assert ai_in_text("blue archive ai", "onikata kayoko")
    assert not ai_in_text("Ai Hoshino fanart by someone", "hoshino ai")
    assert not ai_in_text("kayoko fanart (said, aiming)", "onikata kayoko")


def test_ranking_drops_ai_sites_used_and_tiny_pictures_and_prefers_artists():
    random.seed(1)
    cands = [
        {"url": "https://i.pinimg.com/a.jpg", "page": "https://pinterest.com/pin/1", "title": "kayoko"},
        {"url": "https://i.pximg.net/b.jpg", "page": "https://www.pixiv.net/artworks/2", "title": "kayoko"},
        {"url": "https://image.civitai.com/c.jpg", "page": "https://civitai.com/images/3", "title": "kayoko"},
        {"url": "https://x.example/d.jpg", "page": "https://x.example/d", "title": "kayoko", "width": 120},
        {"url": "https://used.example/e.jpg", "page": "https://used.example/e", "title": "kayoko"},
        {"url": "https://art.example/f.jpg", "page": "https://art.example/f", "title": "kayoko AI generated"},
    ]
    ranked = rank(cands, {"https://used.example/e.jpg"}, "onikata kayoko")
    assert [c["url"] for c in ranked] == ["https://i.pximg.net/b.jpg", "https://i.pinimg.com/a.jpg"]


def test_pictures_are_cropped_square_and_tiny_ones_refused():
    out = Image.open(io.BytesIO(square(png(800, 1200))))
    assert out.size == (512, 512)
    assert square(png(200, 200)) is None
    assert square(png(1200, 200)) is None
