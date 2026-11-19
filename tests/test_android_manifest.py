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
    assert "versionId.length <= 128" in code
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


def test_android_video_timestamp_seek_waits_for_prepared_media() -> None:
    source = Path(__file__).parents[1] / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt"
    code = source.read_text(encoding="utf-8")
    assert "var videoReady by remember { mutableStateOf(false) }" in code
    assert "videoReady = true" in code
    assert "mediaMime?.startsWith(\"video/\") == true && videoReady || audioReady" in code
    assert 'picker.launch(arrayOf("application/json"))' in code


def test_android_audio_player_is_released_when_setup_fails_and_tracks_completion() -> None:
    source = Path(__file__).parents[1] / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt"
    code = source.read_text(encoding="utf-8")
    setup = code.split("LaunchedEffect(mediaUri, mediaMime)", 1)[1].split("DisposableEffect(Unit)", 1)[0]
    assert setup.index("audioPlayer = player") < setup.index("player.setDataSource(context, uri)")
    assert "player.setOnCompletionListener" in setup
    assert "audioPlayer?.release()" in setup


def test_android_reader_searches_all_chapters_and_labels_cross_chapter_results() -> None:
    source = Path(__file__).parents[1] / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt"
    code = source.read_text(encoding="utf-8")
    assert 'label = { Text("Search all chapters") }' in code
    assert "current.chapters.flatMap" in code
    assert ".map { Triple(index, chapter.title, it) }" in code
    assert "if (query.isNotBlank()) {" in code
    assert 'Text(chapterTitle, color = Gold' in code


def test_android_reader_pauses_local_media_when_backgrounded() -> None:
    source = Path(__file__).parents[1] / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt"
    code = source.read_text(encoding="utf-8")
    assert "LifecycleEventObserver" in code
    assert "Lifecycle.Event.ON_STOP" in code
    assert "if (player.isPlaying) player.pause()" in code
    assert "if (view.isPlaying) view.pause()" in code


def test_android_cross_chapter_search_results_can_open_their_chapter() -> None:
    source = Path(__file__).parents[1] / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt"
    code = source.read_text(encoding="utf-8")
    assert "List<Triple<Int, String, Block>>" in code
    assert "flatMapIndexed" in code
    assert "TextButton(onClick = {" in code
    assert "chapterIndex = resultChapterIndex" in code


def test_android_reader_keeps_existing_book_visible_when_replacement_import_fails() -> None:
    source = Path(__file__).parents[1] / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt"
    code = source.read_text(encoding="utf-8")
    header = code.split('Text(current.title', 1)[1].split('Spacer(Modifier.height(8.dp))', 1)[0]
    assert "error?.let" in header
    assert "Color(0xFFFF8C82)" in header


def test_android_reader_restores_chapter_progress_per_textbook_version() -> None:
    root = Path(__file__).parents[1]
    source = root / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt"
    gradle = (root / "apps" / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    code = source.read_text(encoding="utf-8")
    assert 'androidx.datastore:datastore-preferences:1.1.1' in gradle
    assert 'preferencesDataStore(name = "omniintel_reader_progress")' in code
    assert 'intPreferencesKey("chapter:${loadedBook.versionId}")' in code
    assert "readerProgressStore.data.first()" in code
    assert "chapterIndex = savedChapter.coerceIn" in code
    assert "LaunchedEffect(book?.versionId, chapterIndex)" in code
    assert "preferences[progressKey] = chapterIndex" in code
