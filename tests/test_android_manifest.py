from pathlib import Path
import xml.etree.ElementTree as ET


def test_android_reader_requests_network_only_for_consent_gated_online_video_processing() -> None:
    manifest = Path(__file__).parents[1] / "apps" / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    root = ET.parse(manifest).getroot()
    android = "{http://schemas.android.com/apk/res/android}"
    permissions = {
        node.attrib.get(android + "name")
        for node in root.findall("uses-permission")
    }
    assert "android.permission.INTERNET" in permissions
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
    assert 'label = { Text("Search all chapters and notes") }' in code
    assert "current.chapters.flatMap" in code
    assert ".map { Triple(index, chapter.title, it) }" in code
    assert "if (query.isNotBlank() || showBookmarksOnly) {" in code
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


def test_android_reader_restores_paragraph_progress_per_textbook_version() -> None:
    root = Path(__file__).parents[1]
    source = root / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt"
    code = source.read_text(encoding="utf-8")
    assert 'preferencesDataStore(name = "omniintel_reader_progress")' in code
    assert "readerProgressStore.data.first()" in code
    assert "ReaderProgressEntity(versionId, value.coerceAtLeast(0), null, now)" in code
    assert "database.progress().upsert(it)" in code
    assert "lastBlockId" in code
    assert "snapshotFlow { readerListState.firstVisibleItemIndex }" in code
    assert "readerListState.scrollToItem(target" in code
    assert "chapterIndex = (targetChapter ?: savedProgress?.chapterIndex ?: 0)" in code
    assert "intPreferencesKey" not in code


def test_android_reader_migrates_and_persists_block_notes_and_bookmarks_in_room() -> None:
    root = Path(__file__).parents[1]
    source = root / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt"
    code = source.read_text(encoding="utf-8")
    migration = code.split("private suspend fun migrateLegacyReaderPreferences", 1)[1].split("@Composable", 1)[0]
    assert 'name.startsWith("note:")' in migration
    assert 'name.startsWith("bookmark:")' in migration
    assert 'name.startsWith("chapter:")' in migration
    assert "database.annotations().upsertAll" in migration
    assert "database.progress().upsert(it)" in migration
    assert migration.index("database.withTransaction") < migration.index("readerProgressStore.edit")
    assert "it.clear()" in migration
    assert "ReaderAnnotationEntity" in code
    assert "libraryDatabase.annotations().upsert(" in code
    assert "Your private note" in code
    assert "it.length <= 5000" in code
    assert "saved.takeIf { it.isNotBlank() }" in code
    assert "sourceId.length <= 128" in code
    assert "requestedId.length <= 128" in code


def test_android_reader_can_filter_and_search_saved_bookmarks_and_notes() -> None:
    source = Path(__file__).parents[1] / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt"
    code = source.read_text(encoding="utf-8")
    assert 'Search all chapters and notes' in code
    assert 'notesByBlock[block.id]?.contains(query, true) == true' in code
    assert 'matchesQuery && (!showBookmarksOnly || block.id in bookmarkedBlocks)' in code
    assert 'showBookmarksOnly = !showBookmarksOnly' in code
    assert 'current.chapters.flatMapIndexed' in code


def test_android_library_uses_normalized_room_storage_and_persistable_document_access() -> None:
    root = Path(__file__).parents[1]
    app_gradle = (root / "apps" / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    root_gradle = (root / "apps" / "android" / "build.gradle.kts").read_text(encoding="utf-8")
    database = (root / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "ReaderDatabase.kt").read_text(encoding="utf-8")
    activity = (root / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt").read_text(encoding="utf-8")
    assert 'id("org.jetbrains.kotlin.kapt") version "2.0.21" apply false' in root_gradle
    assert 'id("org.jetbrains.kotlin.kapt")' in app_gradle
    assert 'androidx.room:room-runtime:2.6.1' in app_gradle
    assert 'androidx.room:room-ktx:2.6.1' in app_gradle
    assert 'kapt("androidx.room:room-compiler:2.6.1")' in app_gradle
    assert '@Entity(tableName = "library_books")' in database
    assert '@Entity(tableName = "video_imports")' in database
    assert '@Entity(tableName = "textbook_sources"' in database
    assert '@Entity(tableName = "textbook_chapters"' in database
    assert 'tableName = "textbook_blocks"' in database
    assert 'tableName = "textbook_evidence"' in database
    assert 'tableName = "reader_annotations"' in database
    assert 'tableName = "reader_progress"' in database
    assert 'version = 3' in database
    assert 'Migration(1, 2)' in database
    assert 'Migration(2, 3)' in database
    assert 'addMigrations(MIGRATION_1_2, MIGRATION_2_3)' in database
    assert 'Room.databaseBuilder(' in database
    assert 'libraryDatabase.readerContent()' in activity
    assert 'dao.insertBlocks(' in activity
    assert 'dao.insertEvidence(' in activity
    assert 'takePersistableUriPermission' in activity
    assert 'releasePersistableUriPermission' in activity
    assert 'libraryDatabase.libraryBooks().getAll()' in activity
    assert 'openStoredBook(entry.versionId)' in activity
    assert 'libraryDatabase.libraryBooks().delete(entry.versionId)' in activity
    assert 'searchLibrary(term)' in activity




def test_android_online_video_client_requires_https_and_explicit_consent_controls() -> None:
    root = Path(__file__).parents[1]
    manifest = ET.parse(root / "apps" / "android" / "app" / "src" / "main" / "AndroidManifest.xml").getroot()
    android = "{http://schemas.android.com/apk/res/android}"
    permissions = {node.attrib.get(android + "name") for node in manifest.findall("uses-permission")}
    assert "android.permission.INTERNET" in permissions
    remote = (root / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "RemoteVideoApi.kt").read_text(encoding="utf-8")
    activity = (root / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt").read_text(encoding="utf-8")
    assert 'url.protocol == "https"' in remote
    assert 'connection.instanceFollowRedirects = false' in remote
    assert 'approve_network' in remote and 'approve_ai' in remote
    assert "apiTokenDraft.isNotBlank() && networkApproved" in activity
    assert "approveAi = aiApproved" in activity
    assert "networkApproved && aiApproved" not in activity
    assert "getRemoteVideoJob" in activity
    assert "loadBook(Uri.fromFile(cached))" in activity


def test_android_supports_consent_gated_media_upload_as_asr_fallback() -> None:
    root = Path(__file__).parents[1]
    activity = (root / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "MainActivity.kt").read_text(encoding="utf-8")
    client = (root / "apps" / "android" / "app" / "src" / "main" / "java" / "ai" / "omniintel" / "reader" / "RemoteVideoApi.kt").read_text(encoding="utf-8")
    assert "uploadRemoteMedia(context" in activity
    assert "apiTokenDraft.isNotBlank() && uploadConsent" in activity
    assert "approveAi = aiApproved" in activity
    assert "uploadConsent && aiApproved" not in activity
    assert 'uploadPicker.launch(arrayOf("video/*", "audio/*"))' in activity
    assert '"/v1/media/jobs"' in client
    assert "250L * 1024L * 1024L" in client
    assert "setFixedLengthStreamingMode(staged.length())" in client
    assert "staged.inputStream().use" in client
