"""
bakery-social-engine — Tests for core modules.
"""


import pytest


class TestConfig:
    """Test configuration loading."""

    def test_project_root_exists(self):
        from src.config import PROJECT_ROOT
        assert PROJECT_ROOT.exists()

    def test_assets_dir_structure(self):
        from src.config import ASSETS_DIR
        expected_dirs = ["backgrounds", "broll", "fonts", "music", "overlays"]
        for dirname in expected_dirs:
            assert (ASSETS_DIR / dirname).exists(), f"Missing assets/{dirname}/"


class TestDB:
    """Test database operations."""

    @pytest.mark.asyncio
    async def test_init_db(self, tmp_path, monkeypatch):
        """Test database initialization creates tables."""
        import src.db as db_module

        # Use temp path for testing
        test_db = tmp_path / "test.db"
        monkeypatch.setattr(db_module, "DB_PATH", test_db)

        await db_module.init_db()
        assert test_db.exists()

    @pytest.mark.asyncio
    async def test_create_and_get_post(self, tmp_path, monkeypatch):
        """Test creating and retrieving a post."""
        import src.db as db_module

        test_db = tmp_path / "test.db"
        monkeypatch.setattr(db_module, "DB_PATH", test_db)

        await db_module.init_db()

        post_id = await db_module.create_post(
            telegram_msg_id=12345,
            chat_id=67890,
            post_type=db_module.PostType.FEED,
            category="DAILY_SNACK",
            raw_media_paths=["/tmp/photo.jpg"],
        )

        assert post_id is not None
        assert post_id > 0

        post = await db_module.get_post(post_id)
        assert post is not None
        assert post["category"] == "DAILY_SNACK"
        assert post["status"] == "DRAFT"

    @pytest.mark.asyncio
    async def test_update_post(self, tmp_path, monkeypatch):
        """Test updating a post."""
        import src.db as db_module

        test_db = tmp_path / "test.db"
        monkeypatch.setattr(db_module, "DB_PATH", test_db)

        await db_module.init_db()

        post_id = await db_module.create_post(
            post_type=db_module.PostType.REEL,
        )

        await db_module.update_post(
            post_id,
            status=db_module.PostStatus.APPROVED,
            hook_text="Chocolate Overload 🍫",
        )

        post = await db_module.get_post(post_id)
        assert post["status"] == "APPROVED"
        assert post["hook_text"] == "Chocolate Overload 🍫"


class TestAnalyzerSchema:
    """Test the BakeryAnalysis Pydantic model."""

    def test_valid_analysis(self):
        from src.ai.analyzer import BakeryAnalysis

        data = {
            "category": "CUSTOM_CAKE",
            "hook_text_overlay": "Wait for the Cut 🔥",
            "voiceover_script": "Dekho yaar, ye cake maine 3 ghante lagake banaya hai...",
            "instagram_caption": "This beauty took 3 hours 🎂\n\n#CakeReels #AhmedabadBakery",
            "recommended_broll_tag": "chocolate_pour",
        }

        analysis = BakeryAnalysis(**data)
        assert analysis.category == "CUSTOM_CAKE"
        assert analysis.hook_text_overlay == "Wait for the Cut 🔥"

    def test_missing_field_raises(self):
        from src.ai.analyzer import BakeryAnalysis

        with pytest.raises(Exception):
            BakeryAnalysis(category="DAILY_SNACK")  # Missing required fields


class TestKeyboards:
    """Test inline keyboard generation."""

    def test_approval_keyboard(self):
        from src.bot.keyboards import approval_keyboard

        kb = approval_keyboard(42)
        assert len(kb.inline_keyboard) == 2  # Two rows
        assert "publish:42" in kb.inline_keyboard[0][0].callback_data

    def test_schedule_keyboard(self):
        from src.bot.keyboards import schedule_options_keyboard

        kb = schedule_options_keyboard(7)
        # Should have time options + back button
        assert len(kb.inline_keyboard) >= 2
