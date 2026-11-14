from arp.schemas.reporting import TemplateStyleProfile


def test_old_profile_loads_with_null_frame():
    old = {"template_id": "tpl_old", "source_filename": "a.pptx", "slide_width_emu": 12192000, "slide_height_emu": 6858000, "stored_path": "x"}
    p = TemplateStyleProfile.model_validate(old)
    assert p.frame is None
    assert p.frame_error is None
