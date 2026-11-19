from pathlib import Path
import xml.etree.ElementTree as ET


def test_android_reader_manifest_does_not_request_network_access() -> None:
    manifest = Path(__file__).parents[1] / "apps" / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    root = ET.parse(manifest).getroot()
    android = "{http://schemas.android.com/apk/res/android}"
    permissions = {
        node.attrib.get(android + "name")
        for node in root.findall("uses-permission")
    }
    assert "android.permission.INTERNET" not in permissions
    assert "android.permission.ACCESS_NETWORK_STATE" not in permissions
    assert root.find("application") is not None


def test_android_reader_uses_storage_access_framework_without_broad_storage_permission() -> None:
    manifest = Path(__file__).parents[1] / "apps" / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    root = ET.parse(manifest).getroot()
    android = "{http://schemas.android.com/apk/res/android}"
    permissions = {node.attrib.get(android + "name") for node in root.findall("uses-permission")}
    assert "android.permission.READ_EXTERNAL_STORAGE" not in permissions
    assert "android.permission.MANAGE_EXTERNAL_STORAGE" not in permissions


def test_android_reader_bounds_untrusted_json_structure_and_deduplicates_block_ids() -> None:
    source = Path(__file__).parents[1] / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt"
    code = source.read_text(encoding="utf-8")
    assert "MAX_IMPORT_BYTES = 50L * 1024L * 1024L" in code
    assert "size <= MAX_IMPORT_BYTES" in code
    assert "sources.length() in 1..500" in code
    assert "rawChapters.length() in 1..500" in code
    assert "totalBlocks <= 25000" in code
    assert "evidenceArray.length() <= 100" in code
    assert "seenBlockIds.add(stableId)" in code
    assert "transcript_excerpt" in code and "document_elements" in code


def test_android_reader_media_jumps_are_bound_to_the_selected_source() -> None:
    source = Path(__file__).parents[1] / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt"
    code = source.read_text(encoding="utf-8")
    assert "selectedSourceId == evidence.sourceId" in code
    assert "evidence.startMs.coerceIn" in code
    assert "mediaPicker.launch(arrayOf(\"video/*\", \"audio/*\"))" in code
    assert "MediaPlayer()" in code
    assert "VideoView(viewContext)" in code
    assert "Timestamps remain source-local." in code


def test_android_reader_surfaces_media_readiness_and_playback_errors() -> None:
    source = Path(__file__).parents[1] / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt"
    code = source.read_text(encoding="utf-8")
    assert "view.setOnPreparedListener" in code
    assert "view.setOnErrorListener" in code
    assert "view.setOnCompletionListener" in code
    assert "The selected video could not be played" in code
