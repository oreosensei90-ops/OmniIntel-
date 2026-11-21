package ai.omniintel.reader

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.media.MediaPlayer
import android.widget.MediaController
import android.widget.VideoView
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.runtime.snapshotFlow
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.preferencesDataStore
import androidx.room.withTransaction
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.collect
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext
import kotlinx.coroutines.delay
import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction

private val Ink = Color(0xFF111318)
private val Panel = Color(0xFF1B1F27)
private val Gold = Color(0xFFE2BD71)
private val Muted = Color(0xFF9BA3B2)
private const val MAX_IMPORT_BYTES = 50L * 1024L * 1024L
private val Context.readerProgressStore by preferencesDataStore(name = "omniintel_reader_progress")


private suspend fun migrateLegacyReaderPreferences(context: Context, database: ReaderDatabase) {
    val migrationKey = "legacy_preferences_to_room_v1"
    if (database.migrations().find(migrationKey) != null) return
    val old = context.readerProgressStore.data.first()
    val annotations = linkedMapOf<Pair<String, String>, ReaderAnnotationEntity>()
    val progress = mutableListOf<ReaderProgressEntity>()
    val now = System.currentTimeMillis()
    for ((key, value) in old.asMap()) {
        val name = key.name
        when {
            name.startsWith("note:") -> {
                val split = name.indexOf(':', 5)
                if (split > 5 && split < name.lastIndex) {
                    val versionId = name.substring(5, split); val blockId = name.substring(split + 1)
                    if (value is String) {
                        val pair = versionId to blockId
                        val previous = annotations[pair] ?: ReaderAnnotationEntity(versionId, blockId, null, false, now)
                        annotations[pair] = previous.copy(note = value, updatedAtEpochMs = now)
                    }
                }
            }
            name.startsWith("bookmark:") -> {
                val split = name.indexOf(':', 9)
                if (split > 9 && split < name.lastIndex) {
                    val versionId = name.substring(9, split); val blockId = name.substring(split + 1)
                    if (value is Boolean) {
                        val pair = versionId to blockId
                        val previous = annotations[pair] ?: ReaderAnnotationEntity(versionId, blockId, null, false, now)
                        annotations[pair] = previous.copy(bookmarked = value, updatedAtEpochMs = now)
                    }
                }
            }
            name.startsWith("chapter:") -> {
                val versionId = name.removePrefix("chapter:")
                if (versionId.isNotBlank() && value is Int) progress += ReaderProgressEntity(versionId, value.coerceAtLeast(0), null, now)
            }
        }
    }
    database.withTransaction {
        database.annotations().upsertAll(annotations.values.toList())
        progress.forEach { database.progress().upsert(it) }
        database.migrations().insert(ReaderMigrationEntity(migrationKey, now))
    }
    context.readerProgressStore.edit { it.clear() }
}



data class ReaderSource(val id: String, val title: String)
data class Evidence(val sourceId: String, val source: String, val locator: String, val startMs: Long?, val excerpt: String)
data class Block(
    val id: String,
    val type: String,
    val text: String,
    val provenance: String,
    val evidence: List<Evidence>,
    val studyFront: String = "",
    val studyBack: String = ""
)
data class Book(val title: String, val versionId: String, val sources: List<ReaderSource>, val chapters: List<ReaderChapter>)
data class ReaderChapter(val title: String, val blocks: List<Block>)

class MainActivity : ComponentActivity() {
    private var sharedVideoUrl by mutableStateOf<String?>(null)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        sharedVideoUrl = extractYouTubeUrl(intent)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(
                primary = Gold, onPrimary = Ink, background = Ink, surface = Panel,
                onBackground = Color(0xFFF1F2F4), onSurface = Color(0xFFF1F2F4)
            )) {
                Surface(Modifier.fillMaxSize(), color = Ink) {
                    ReaderScreen(sharedUrl = sharedVideoUrl) { uri, callback ->
                        lifecycleScope.launch {
                            callback(withContext(Dispatchers.IO) { runCatching { parse(uri) } })
                        }
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        sharedVideoUrl = extractYouTubeUrl(intent)
    }

    private fun parse(uri: Uri): Book {
        val bytes = contentResolver.openInputStream(uri).use { stream ->
            requireNotNull(stream) { "Unable to open selected file." }
            val out = ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            var size = 0L
            while (true) {
                val count = stream.read(buffer)
                if (count < 0) break
                size += count
                require(size <= MAX_IMPORT_BYTES) { "Reader export exceeds 50 MiB." }
                out.write(buffer, 0, count)
            }
            out.toByteArray()
        }
        val raw = Charsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
            .decode(ByteBuffer.wrap(bytes))
            .toString()
        val root = JSONObject(raw)
        val version = root.optJSONObject("version") ?: error("Missing textbook version.")
        val versionId = version.optString("id")
        require(versionId.isNotBlank() && versionId.length <= 128) { "Textbook version ID is missing or invalid." }
        val sourcesById = mutableMapOf<String, ReaderSource>()
        val sources = root.optJSONArray("sources") ?: error("Missing course sources.")
        require(sources.length() in 1..500) { "Reader export must contain between 1 and 500 sources." }
        for (i in 0 until sources.length()) {
            val source = sources.getJSONObject(i)
            val sourceId = source.optString("source_id")
            require(sourceId.isNotBlank() && sourceId.length <= 128 && !sourcesById.containsKey(sourceId)) {
                "Course source IDs must be non-empty and unique."
            }
            sourcesById[sourceId] = ReaderSource(sourceId, source.optString("title", "Course source"))
        }
        val rawChapters = root.optJSONArray("chapters") ?: error("Missing chapters.")
        require(rawChapters.length() in 1..500) { "Reader export must contain between 1 and 500 chapters." }
        val seenBlockIds = mutableSetOf<String>()
        var totalBlocks = 0
        val chapters = (0 until rawChapters.length()).map { i ->
            val entry = rawChapters.getJSONObject(i)
            val chapter = entry.optJSONObject("chapter") ?: error("Chapter metadata is missing.")
            val rawBlocks = entry.optJSONArray("blocks") ?: error("Chapter blocks are missing.")
            totalBlocks += rawBlocks.length()
            require(totalBlocks <= 25000) { "Reader export exceeds the 25,000 block safety limit." }
            val blocks = (0 until rawBlocks.length()).map { j ->
                val block = rawBlocks.getJSONObject(j)
                val blockType = block.optString("block_type")
                require(blockType.isNotBlank()) { "A textbook block is missing its type." }
                val content = block.optJSONObject("content") ?: error("Block content is missing.")
                val evidenceArray = block.optJSONArray("evidence") ?: error("Block evidence list is missing.")
                require(evidenceArray.length() <= 100) { "A block exceeds the 100 evidence-reference safety limit." }
                val evidence = (0 until evidenceArray.length()).map { k ->
                    val item = evidenceArray.getJSONObject(k)
                    require((item.optJSONArray("transcript_excerpt")?.length() ?: 0) <= 40) {
                        "An evidence reference exceeds the transcript excerpt safety limit."
                    }
                    require((item.optJSONArray("document_elements")?.length() ?: 0) <= 100) {
                        "An evidence reference exceeds the document element safety limit."
                    }
                    val page = item.optJSONObject("document_page")
                    val excerpts = item.optJSONArray("transcript_excerpt") ?: JSONArray()
                    val excerpt = (0 until excerpts.length()).map { n ->
                        excerpts.getJSONObject(n).optString("text")
                    }.joinToString(" ")
                    val sourceId = item.optString("source_id")
                    require(sourcesById.containsKey(sourceId)) { "Evidence references an unknown course source." }
                    val pageNo = if (page == null || page.isNull("page_number")) null else page.optInt("page_number")
                    val start = if (item.isNull("local_start_ms")) null else item.optLong("local_start_ms")
                    Evidence(
                        sourceId,
                        sourcesById.getValue(sourceId).title,
                        pageNo?.let { "page " + it } ?: start?.let { "%.1fs".format(it / 1000.0) } ?: "source reference",
                        start,
                        excerpt.ifBlank { page?.optString("text_content").orEmpty().take(700) }
                    )
                }
                val text = listOf("text", "body", "definition", "description", "code", "latex", "expression", "term")
                    .firstNotNullOfOrNull { key -> content.optString(key).takeIf { it.isNotBlank() } }.orEmpty()
                val requestedId = block.optString("id").takeIf { it.isNotBlank() } ?: "${i}-${j}"
                require(requestedId.length <= 128) { "A textbook block ID exceeds 128 characters." }
                var stableId = requestedId
                var suffix = 1
                while (!seenBlockIds.add(stableId)) {
                    stableId = "${requestedId}@${i}-${j}-${suffix++}"
                }
                val studyFront = when (blockType.uppercase()) {
                    "DEFINITION" -> content.optString("term").ifBlank { content.optString("title") }
                    "EXERCISE" -> content.optString("prompt").ifBlank {
                        content.optString("question").ifBlank { content.optString("text").ifBlank { content.optString("body") } }
                    }
                    "FLASHCARD", "QUESTION" -> content.optString("front").ifBlank {
                        content.optString("question").ifBlank { content.optString("prompt").ifBlank { content.optString("term") } }
                    }
                    else -> ""
                }
                val studyBack = when (blockType.uppercase()) {
                    "DEFINITION" -> content.optString("definition").ifBlank { content.optString("text").ifBlank { content.optString("body") } }
                    "EXERCISE" -> content.optString("answer").ifBlank {
                        content.optString("solution").ifBlank { content.optString("expected_answer") }
                    }
                    "FLASHCARD", "QUESTION" -> content.optString("back").ifBlank {
                        content.optString("answer").ifBlank { content.optString("definition").ifBlank { content.optString("solution") } }
                    }
                    else -> ""
                }
                Block(
                    stableId,
                    blockType,
                    text,
                    block.optString("provenance", "UNSPECIFIED"),
                    evidence,
                    studyFront,
                    studyBack
                )
            }
            ReaderChapter(chapter.optString("title", "Chapter ${i + 1}"), blocks)
        }
        require(chapters.isNotEmpty()) { "This textbook has no readable chapters." }
        return Book(version.optString("textbook_title", version.optString("title", "Course textbook")), versionId, sourcesById.values.toList(), chapters)
    }
}

@Composable
private fun ReaderScreen(sharedUrl: String? = null, open: (Uri, (Result<Book>) -> Unit) -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val scope = rememberCoroutineScope()
    var book by remember { mutableStateOf<Book?>(null) }
    val libraryDatabase = remember { ReaderDatabase.get(context) }
    var libraryBooks by remember { mutableStateOf<List<LibraryBookEntity>>(emptyList()) }
    var librarySearchQuery by remember { mutableStateOf("") }
    var librarySearchResults by remember { mutableStateOf<List<LibrarySearchResult>>(emptyList()) }
    var resumeBlockId by remember { mutableStateOf<String?>(null) }
    val readerListState = rememberLazyListState()
    var videoImports by remember { mutableStateOf<List<VideoImportEntity>>(emptyList()) }
    var videoUrlDraft by remember { mutableStateOf("") }
    var videoImportMessage by remember { mutableStateOf<String?>(null) }
    var apiBaseDraft by remember {
        val savedApiBase = context.getSharedPreferences("omniintel_remote", Context.MODE_PRIVATE)
            .getString("api_base", null)
        mutableStateOf(savedApiBase?.takeIf { it.isNotBlank() } ?: "https://omniintel-api.scrbaba502.workers.dev")
    }
    var apiTokenDraft by remember { mutableStateOf("") }
    var networkApproved by remember { mutableStateOf(false) }
    var aiApproved by remember { mutableStateOf(false) }
    var onlineBusy by remember { mutableStateOf(false) }
    var uploadUri by remember { mutableStateOf<Uri?>(null) }
    var uploadConsent by remember { mutableStateOf(false) }
    var visualApproved by remember { mutableStateOf(false) }
    var annotationBackupMessage by remember { mutableStateOf<String?>(null) }
    var showStudy by remember { mutableStateOf(false) }
    var chapterIndex by remember { mutableIntStateOf(0) }
    var query by remember { mutableStateOf("") }
    var showBookmarksOnly by remember { mutableStateOf(false) }
    var notesByBlock by remember { mutableStateOf<Map<String, String>>(emptyMap()) }
    var bookmarkedBlocks by remember { mutableStateOf<Set<String>>(emptySet()) }
    var editingBlockId by remember { mutableStateOf<String?>(null) }
    var noteDraft by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var selectedSourceId by remember { mutableStateOf<String?>(null) }
    var mediaUri by remember { mutableStateOf<Uri?>(null) }
    var mediaMime by remember { mutableStateOf<String?>(null) }
    var mediaStatus by remember { mutableStateOf("Select the exact course source before attaching media.") }
    var sourceMenuExpanded by remember { mutableStateOf(false) }
    var videoView by remember { mutableStateOf<VideoView?>(null) }
    var audioPlayer by remember { mutableStateOf<MediaPlayer?>(null) }
    var audioReady by remember { mutableStateOf(false) }
    var videoReady by remember { mutableStateOf(false) }
    var audioPlaying by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        libraryBooks = runCatching {
            withContext(Dispatchers.IO) {
                migrateLegacyReaderPreferences(context, libraryDatabase)
                libraryDatabase.libraryBooks().getAll()
            }
        }.getOrElse {
            error = "The on-device library could not be loaded or legacy reader data could not be migrated safely."
            emptyList()
        }
    }
    LaunchedEffect(librarySearchQuery) {
        val term = librarySearchQuery.trim()
        librarySearchResults = if (term.isBlank()) emptyList() else runCatching {
            withContext(Dispatchers.IO) { libraryDatabase.libraryBooks().searchLibrary(term) }
        }.getOrDefault(emptyList())
    }
    LaunchedEffect(Unit) {
        videoImports = runCatching {
            withContext(Dispatchers.IO) { libraryDatabase.videoImports().getAll() }
        }.getOrDefault(emptyList())
    }
    LaunchedEffect(sharedUrl) {
        if (!sharedUrl.isNullOrBlank()) {
            videoUrlDraft = sharedUrl
            videoImportMessage = "YouTube link received. Review it and add it to your queue."
        }
    }

    fun displayLoadedBook(loadedBook: Book, savedProgress: ReaderProgressEntity?, savedAnnotations: List<ReaderAnnotationEntity>, warning: String? = null, targetBlockId: String? = null) {
        notesByBlock = savedAnnotations.mapNotNull { row -> row.note?.takeIf { it.isNotBlank() }?.let { row.blockId to it } }.toMap()
        bookmarkedBlocks = savedAnnotations.filter { it.bookmarked }.map { it.blockId }.toSet()
        editingBlockId = null; noteDraft = ""; book = loadedBook
        val targetChapter = targetBlockId?.let { id ->
            loadedBook.chapters.indexOfFirst { chapter -> chapter.blocks.any { it.id == id } }
        }?.takeIf { it >= 0 }
        chapterIndex = (targetChapter ?: savedProgress?.chapterIndex ?: 0).coerceIn(0, loadedBook.chapters.lastIndex)
        resumeBlockId = targetBlockId ?: savedProgress?.lastBlockId
        query = ""; showBookmarksOnly = false; error = warning
        selectedSourceId = null; mediaUri = null; mediaMime = null
        audioPlayer?.release(); audioPlayer = null; audioReady = false; audioPlaying = false; videoReady = false
        videoView?.stopPlayback(); videoView = null
        mediaStatus = "Select the exact course source, then attach only the matching local media file."
    }

    fun loadBook(uri: Uri) {
        open(uri) { result ->
            result.onSuccess { loadedBook ->
                scope.launch {
                    runCatching {
                        val hasGrant = context.contentResolver.persistedUriPermissions.any { it.uri == uri && it.isReadPermission } ||
                            runCatching { context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) }.isSuccess
                        val now = System.currentTimeMillis()
                        val saved = withContext(Dispatchers.IO) {
                            libraryDatabase.withTransaction {
                                val previous = libraryDatabase.libraryBooks().find(loadedBook.versionId)
                                libraryDatabase.libraryBooks().upsert(
                                    LibraryBookEntity(loadedBook.versionId, loadedBook.title, uri.toString(),
                                        loadedBook.sources.size, loadedBook.chapters.size,
                                        previous?.importedAtEpochMs ?: now, now)
                                )
                                val dao = libraryDatabase.readerContent()
                                dao.deleteChapters(loadedBook.versionId); dao.deleteSources(loadedBook.versionId)
                                dao.insertSources(loadedBook.sources.map { TextbookSourceEntity(loadedBook.versionId, it.id, it.title) })
                                dao.insertChapters(loadedBook.chapters.mapIndexed { index, ch -> TextbookChapterEntity(loadedBook.versionId, index, ch.title) })
                                dao.insertBlocks(loadedBook.chapters.flatMapIndexed { ci, ch ->
                                    ch.blocks.mapIndexed { bi, block ->
                                        TextbookBlockEntity(loadedBook.versionId, block.id, ci, bi, block.type, block.text, block.provenance, block.studyFront, block.studyBack)
                                    }
                                })
                                dao.insertEvidence(loadedBook.chapters.flatMap { ch ->
                                    ch.blocks.flatMap { block ->
                                        block.evidence.mapIndexed { ei, ev ->
                                            TextbookEvidenceEntity(loadedBook.versionId, block.id, ei, ev.sourceId, ev.source, ev.locator, ev.startMs, ev.excerpt)
                                        }
                                    }
                                })
                            }
                            Triple(libraryDatabase.progress().find(loadedBook.versionId),
                                libraryDatabase.annotations().forVersion(loadedBook.versionId),
                                libraryDatabase.libraryBooks().getAll())
                        }
                        libraryBooks = saved.third
                        displayLoadedBook(loadedBook, saved.first, saved.second,
                            if (hasGrant) null else "Imported into the on-device library. The original file permission is temporary, but the stored textbook remains available offline.")
                    }.onFailure { error = "Could not save the textbook safely to the on-device library: " + (it.message ?: "storage error") }
                }
            }.onFailure { error = it.message ?: "Could not open reader export." }
        }
    }

    fun openStoredBook(versionId: String, targetBlockId: String? = null) {
        scope.launch {
            runCatching {
                val stored = withContext(Dispatchers.IO) {
                    val metadata = requireNotNull(libraryDatabase.libraryBooks().find(versionId))
                    val dao = libraryDatabase.readerContent()
                    val sources = dao.sources(versionId); val chapters = dao.chapters(versionId)
                    val blocks = dao.blocks(versionId); val evidence = dao.evidence(versionId).groupBy { it.blockId }
                    require(chapters.isNotEmpty() && blocks.isNotEmpty()) { "Stored textbook content is unavailable." }
                    val loaded = Book(metadata.title, versionId, sources.map { ReaderSource(it.sourceId, it.title) },
                        chapters.map { chapter ->
                            ReaderChapter(chapter.title, blocks.filter { it.chapterIndex == chapter.chapterIndex }.map { block ->
                                Block(block.blockId, block.blockType, block.text, block.provenance,
                                    evidence[block.blockId].orEmpty().map { ev -> Evidence(ev.sourceId, ev.sourceTitle, ev.locator, ev.startMs, ev.excerpt) },
                                    block.studyFront, block.studyBack)
                            })
                        })
                    Triple(loaded, libraryDatabase.progress().find(versionId), libraryDatabase.annotations().forVersion(versionId))
                }
                displayLoadedBook(stored.first, stored.second, stored.third, targetBlockId = targetBlockId)
                libraryBooks = withContext(Dispatchers.IO) { libraryDatabase.libraryBooks().getAll() }
                librarySearchQuery = ""
            }.onFailure {
                val metadata = withContext(Dispatchers.IO) { libraryDatabase.libraryBooks().find(versionId) }
                if (metadata != null) loadBook(Uri.parse(metadata.documentUri))
                else error = "Could not reopen the saved textbook: " + (it.message ?: "content unavailable")
            }
        }
    }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) loadBook(uri)
    }
    val queueExporter = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/json")
    ) { uri ->
        if (uri != null) {
            scope.launch {
                runCatching {
                    withContext(Dispatchers.IO) {
                        val stream = context.contentResolver.openOutputStream(uri)
                            ?: error("Unable to write the selected queue file.")
                        stream.bufferedWriter(Charsets.UTF_8).use { writer ->
                            writer.write(videoQueueJson(videoImports))
                        }
                    }
                }.onSuccess {
                    videoImportMessage = "Queue exported. Transfer the JSON to the local OmniIntel engine to process captions."
                }.onFailure {
                    videoImportMessage = "Queue export failed: " + (it.message ?: "storage error")
                }
            }
        }
    }
    val annotationBackupExporter = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/json")
    ) { uri ->
        if (uri != null) scope.launch {
            runCatching {
                val rows = withContext(Dispatchers.IO) { libraryDatabase.annotations().getAll() }
                val json = annotationBackupJson(rows)
                withContext(Dispatchers.IO) {
                    val output = context.contentResolver.openOutputStream(uri)
                        ?: error("Unable to write the selected backup file.")
                    output.bufferedWriter(Charsets.UTF_8).use { it.write(json) }
                }
                rows.size
            }.onSuccess { annotationBackupMessage = "Backed up $it annotation records." }
             .onFailure { annotationBackupMessage = "Backup failed: " + (it.message ?: "storage error") }
        }
    }
    val annotationBackupImporter = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri ->
        if (uri != null) scope.launch {
            runCatching {
                val raw = withContext(Dispatchers.IO) {
                    context.contentResolver.openInputStream(uri).use { input ->
                        requireNotNull(input) { "Unable to open the selected backup." }
                        val output = ByteArrayOutputStream()
                        val buffer = ByteArray(8192)
                        var total = 0
                        while (true) {
                            val count = input.read(buffer)
                            if (count < 0) break
                            total += count
                            require(total <= 5 * 1024 * 1024) { "Annotation backup exceeds 5 MiB." }
                            output.write(buffer, 0, count)
                        }
                        output.toString(Charsets.UTF_8.name())
                    }
                }
                val records = parseAnnotationBackup(raw)
                val valid = withContext(Dispatchers.IO) {
                    val currentRows = libraryDatabase.annotations().getAll().associateBy { it.versionId to it.blockId }
                    val accepted = records.filter { record ->
                        val knownBlock = libraryDatabase.readerContent().blocks(record.versionId)
                            .any { it.blockId == record.blockId }
                        knownBlock && (currentRows[record.versionId to record.blockId]?.updatedAtEpochMs
                            ?: Long.MIN_VALUE) <= record.updatedAtEpochMs
                    }
                    libraryDatabase.withTransaction {
                        libraryDatabase.annotations().upsertAll(accepted)
                    }
                    accepted.size
                }
                valid
            }.onSuccess { annotationBackupMessage = "Restored or merged $it annotation records. Newer local edits were preserved." }
             .onFailure { annotationBackupMessage = "Restore failed: " + (it.message ?: "invalid backup") }
        }
    }
    val uploadPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            runCatching {
                context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            uploadUri = uri
            uploadConsent = false
            visualApproved = false
            videoImportMessage = "Media selected. Approve upload and AI processing below."
        }
    }
    val mediaPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        if (selectedSourceId == null) {
            mediaStatus = "Select the exact course source first."
        } else {
            val mime = context.contentResolver.getType(uri).orEmpty()
            if (mime.startsWith("video/") || mime.startsWith("audio/")) {
                videoView?.stopPlayback()
                videoView = null
                audioPlayer?.release()
                audioPlayer = null
                audioReady = false
                audioPlaying = false
                videoReady = false
                mediaUri = uri
                mediaMime = mime
                mediaStatus = "Attached locally to the selected source. Timestamps remain source-local."
            } else {
                mediaStatus = "Choose a supported audio or video file."
            }
        }
    }
    LaunchedEffect(mediaUri, mediaMime) {
        audioPlayer?.release()
        audioPlayer = null
        audioReady = false
        audioPlaying = false
        val uri = mediaUri
        if (uri != null && mediaMime?.startsWith("audio/") == true) {
            runCatching {
                MediaPlayer().also { player ->
                    audioPlayer = player
                    player.setDataSource(context, uri)
                    player.setOnPreparedListener {
                        audioReady = true
                        mediaStatus = "Audio ready · selected source only."
                    }
                    player.setOnCompletionListener {
                        audioPlaying = false
                        mediaStatus = "Audio playback complete."
                    }
                    player.setOnErrorListener { _, _, _ ->
                        audioReady = false
                        audioPlaying = false
                        mediaStatus = "The selected audio file could not be played."
                        true
                    }
                    player.prepareAsync()
                }
            }.onFailure {
                audioPlayer?.release()
                audioPlayer = null
                mediaStatus = "The selected audio file could not be opened."
            }
        }
    }
    LaunchedEffect(book?.versionId) {
        val currentBook = book ?: return@LaunchedEffect
        runCatching {
            val rows = withContext(Dispatchers.IO) { libraryDatabase.annotations().forVersion(currentBook.versionId) }
            notesByBlock = rows.mapNotNull { row -> row.note?.takeIf { it.isNotBlank() }?.let { row.blockId to it } }.toMap()
            bookmarkedBlocks = rows.filter { it.bookmarked }.map { it.blockId }.toSet()
        }.onFailure { error = "Could not restore local notes and bookmarks from the on-device library." }
    }
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) {
                audioPlayer?.let { player -> runCatching { if (player.isPlaying) player.pause() } }
                audioPlaying = false
                videoView?.let { view -> runCatching { if (view.isPlaying) view.pause() } }
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    DisposableEffect(Unit) {
        onDispose {
            audioPlayer?.release()
            videoView?.stopPlayback()
        }
    }
    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().background(Panel).padding(18.dp),
            horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text("OMNIINTEL", color = Color.White, fontWeight = FontWeight.Black, letterSpacing = 2.sp)
                Text("VIDEO → NOTES · READER", color = Gold, fontSize = 10.sp, letterSpacing = 2.sp)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (book != null) {
                    TextButton(onClick = { showStudy = true }) { Text("Study", color = Gold) }
                    TextButton(onClick = {
                        audioPlayer?.release(); audioPlayer = null
                        videoView?.stopPlayback(); videoView = null
                        mediaUri = null; mediaMime = null; selectedSourceId = null
                        book = null
                    }) { Text("Library", color = Gold) }
                }
                OutlinedButton(onClick = { picker.launch(arrayOf("application/json")) }) {
                    Text(if (book == null) "Import textbook" else "Open another")
                }
                TextButton(onClick = { annotationBackupExporter.launch("omniintel-annotations-backup.json") }) {
                    Text("Backup", color = Gold)
                }
            }
        }
        val current = book
        if (current == null) {
            Column(
                Modifier.fillMaxSize().padding(28.dp),
                verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text("Your learning library.", fontSize = 32.sp, fontWeight = FontWeight.Bold)
                Text("On your device.", fontSize = 32.sp, color = Gold, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(18.dp))
                Text("Open an OmniIntel reader JSON export. It stays on this device; no account or network connection is required.", color = Muted)
                Spacer(Modifier.height(20.dp))
                Button(onClick = { picker.launch(arrayOf("application/json")) }) { Text("Choose reader export") }
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { annotationBackupExporter.launch("omniintel-annotations-backup.json") }) {
                        Text("Back up notes")
                    }
                    OutlinedButton(onClick = { annotationBackupImporter.launch(arrayOf("application/json")) }) {
                        Text("Restore notes")
                    }
                }
                annotationBackupMessage?.let { Text(it, color = Gold, fontSize = 12.sp) }
                Spacer(Modifier.height(24.dp))
                Text("LEARN FROM VIDEO", color = Gold, fontSize = 11.sp, letterSpacing = 2.sp)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = videoUrlDraft,
                    onValueChange = { videoUrlDraft = it; videoImportMessage = null },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("YouTube video URL") },
                    placeholder = { Text("Paste a YouTube link") }
                )
                Spacer(Modifier.height(8.dp))
                Button(
                    onClick = {
                        val parsed = parseYouTubeUrl(videoUrlDraft)
                        if (parsed == null) {
                            videoImportMessage = "That link isn't a supported YouTube video URL."
                        } else {
                            scope.launch {
                                runCatching {
                                    withContext(Dispatchers.IO) {
                                        libraryDatabase.videoImports().insertIfAbsent(
                                            VideoImportEntity(
                                                videoId = parsed.videoId,
                                                url = parsed.url,
                                                createdAtEpochMs = System.currentTimeMillis(),
                                                status = "QUEUED"
                                            )
                                        )
                                        libraryDatabase.videoImports().getAll()
                                    }
                                }.onSuccess { saved ->
                                    videoImports = saved
                                    videoUrlDraft = ""
                                    videoImportMessage = "Added to the local queue. Use online processing or export the queue for the local engine."
                                }.onFailure {
                                    videoImportMessage = "Could not save this video to the on-device queue."
                                }
                            }
                        }
                    },
                    enabled = videoUrlDraft.isNotBlank()
                ) { Text("Add video to queue") }
                videoImportMessage?.let {
                    Text(it, color = Muted, fontSize = 11.sp, modifier = Modifier.padding(top = 6.dp))
                }
                Spacer(Modifier.height(12.dp))
                Text("ONLINE VIDEO PROCESSING", color = Gold, fontSize = 10.sp, letterSpacing = 2.sp)
                OutlinedTextField(
                    value = apiBaseDraft,
                    onValueChange = {
                        apiBaseDraft = it
                        context.getSharedPreferences("omniintel_remote", Context.MODE_PRIVATE)
                            .edit().putString("api_base", it).apply()
                    },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("OmniIntel API HTTPS address") },
                    placeholder = { Text("https://your-server.example") }
                )
                OutlinedTextField(
                    value = apiTokenDraft,
                    onValueChange = { apiTokenDraft = it },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("OmniIntel API access token") },
                    placeholder = { Text("Paste token (Bearer prefix optional)") },
                    supportingText = { Text("Paste the token value only. The app adds the Bearer authorization prefix automatically.") }
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(checked = networkApproved, onCheckedChange = { networkApproved = it })
                    Text("I authorize public video metadata and caption retrieval.", color = Muted, fontSize = 11.sp)
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(checked = aiApproved, onCheckedChange = { aiApproved = it })
                    Text("I authorize sending the transcript to the AI provider configured on my processing machine.", color = Muted, fontSize = 11.sp)
                }
                Button(
                    enabled = !onlineBusy && videoUrlDraft.isNotBlank() && apiBaseDraft.isNotBlank() &&
                        apiTokenDraft.isNotBlank() && networkApproved,
                    onClick = {
                        val parsed = parseYouTubeUrl(videoUrlDraft)
                        if (parsed == null) {
                            videoImportMessage = "That link isn't a supported YouTube video URL."
                        } else {
                            onlineBusy = true
                            videoImportMessage = "Submitting video to OmniIntel…"
                            val apiBase = apiBaseDraft
                            val apiToken = apiTokenDraft
                            scope.launch {
                                try {
                                    val created = withContext(Dispatchers.IO) {
                                        submitRemoteVideoJob(apiBase, apiToken, parsed.url, approveAi = aiApproved)
                                    }
                                    val statusPath = created.getString("status_url")
                                    val jobId = created.getString("job_id")
                                    videoImportMessage = "Job $jobId queued · fetching captions and generating notes…"
                                    var attempts = 0
                                    var readerJson: String? = null
                                    while (attempts < 1800 && readerJson == null) {
                                        delay(2_000)
                                        val status = withContext(Dispatchers.IO) {
                                            getRemoteVideoJob(apiBase, apiToken, statusPath)
                                        }
                                        when (status.optString("status")) {
                                            "COMPLETED" -> {
                                                val resultUrl = status.optString("result_url")
                                                if (!resultUrl.startsWith("https://")) error("The server completed without a reader download URL.")
                                                readerJson = downloadRemoteReaderJson(resultUrl)
                                            }
                                            "FAILED" -> error(status.optString("error").ifBlank { "Video processing failed." })
                                            else -> {
                                                val statusText = status.optString("status")
                                                videoImportMessage = "Processing video · $statusText · job $jobId"
                                            }
                                        }
                                        attempts++
                                    }
                                    val json = readerJson ?: error("The job is still processing. Check again later.")
                                    val cached = File(context.cacheDir, "omniintel-$jobId.json")
                                    withContext(Dispatchers.IO) { cached.writeText(json, Charsets.UTF_8) }
                                    loadBook(Uri.fromFile(cached))
                                    videoImportMessage = "Notes generated. Importing into your on-device library…"
                                } catch (failure: Throwable) {
                                    videoImportMessage = failure.message ?: "Online video processing failed."
                                } finally {
                                    onlineBusy = false
                                }
                            }
                        }
                    }
                ) { Text(if (onlineBusy) "Processing…" else "Generate video notes online") }
                Button(
                    enabled = !onlineBusy,
                    onClick = { uploadPicker.launch(arrayOf("video/*", "audio/*")) }
                ) { Text(uploadUri?.lastPathSegment?.let { "Selected media: $it" } ?: "Choose media for transcription") }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(checked = uploadConsent, onCheckedChange = { uploadConsent = it })
                    Text("I authorize uploading this media to my OmniIntel server for transcription.", color = Muted, fontSize = 11.sp)
                }
                if (uploadUri?.let { context.contentResolver.getType(it)?.startsWith("video/") == true } == true) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = visualApproved, onCheckedChange = { visualApproved = it })
                        Text("I separately approve bounded local frame sampling for a reviewable visual timeline. No frame or transcript link is auto-accepted.", color = Muted, fontSize = 11.sp)
                    }
                }
                Button(
                    enabled = !onlineBusy && uploadUri != null && apiBaseDraft.isNotBlank() &&
                        apiTokenDraft.isNotBlank() && uploadConsent,
                    onClick = {
                        val selectedUri = uploadUri
                        if (selectedUri != null) {
                            onlineBusy = true
                            videoImportMessage = "Uploading media to OmniIntel…"
                            val apiBase = apiBaseDraft
                            val apiToken = apiTokenDraft
                            scope.launch {
                                try {
                                    val created = withContext(Dispatchers.IO) {
                                        uploadRemoteMedia(context, apiBase, apiToken, selectedUri, approveAi = aiApproved, approveVisual = visualApproved)
                                    }
                                    val statusPath = created.getString("status_url")
                                    val jobId = created.getString("job_id")
                                    videoImportMessage = "Upload accepted · transcribing media · job $jobId"
                                    var attempts = 0
                                    var readerJson: String? = null
                                    while (attempts < 1800 && readerJson == null) {
                                        delay(2_000)
                                        val status = withContext(Dispatchers.IO) {
                                            getRemoteVideoJob(apiBase, apiToken, statusPath)
                                        }
                                        when (status.optString("status")) {
                                            "COMPLETED" -> {
                                                val resultUrl = status.optString("result_url")
                                                if (!resultUrl.startsWith("https://")) error("The server completed without a reader download URL.")
                                                readerJson = downloadRemoteReaderJson(resultUrl)
                                            }
                                            "FAILED" -> error(status.optString("error").ifBlank { "Media transcription failed." })
                                            else -> {
                                                val statusText = status.optString("status")
                                                videoImportMessage = "Transcribing media · $statusText · job $jobId"
                                            }
                                        }
                                        attempts++
                                    }
                                    val json = readerJson ?: error("The job is still processing. Check again later.")
                                    val cached = File(context.cacheDir, "omniintel-media-$jobId.json")
                                    withContext(Dispatchers.IO) { cached.writeText(json, Charsets.UTF_8) }
                                    loadBook(Uri.fromFile(cached))
                                    uploadUri = null
                                    uploadConsent = false
                                    visualApproved = false
                                    videoImportMessage = "AI notes generated. Importing into your on-device library…"
                                } catch (failure: Throwable) {
                                    videoImportMessage = failure.message ?: "Media upload or transcription failed."
                                } finally {
                                    onlineBusy = false
                                }
                            }
                        }
                    }
                ) { Text(if (onlineBusy) "Processing…" else "Upload and generate notes") }
                if (videoImports.isNotEmpty()) {
                    Text(
                        "VIDEO QUEUE · ${videoImports.size}",
                        color = Gold, fontSize = 10.sp, letterSpacing = 2.sp,
                        modifier = Modifier.padding(top = 16.dp, bottom = 6.dp)
                    )
                    OutlinedButton(
                        onClick = { queueExporter.launch("omniintel-video-queue.json") }
                    ) { Text("Export processing queue") }
                    videoImports.take(4).forEach { item ->
                        Card(
                            modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp),
                            colors = CardDefaults.cardColors(containerColor = Panel)
                        ) {
                            Column(Modifier.padding(10.dp)) {
                                Text(item.url, color = Color.White, fontSize = 11.sp)
                                Text("QUEUED · ready for online processing or local handoff", color = Muted, fontSize = 9.sp)
                            }
                        }
                    }
                }
                error?.let { Text(it, color = Color(0xFFFF8C82), modifier = Modifier.padding(top = 12.dp)) }
                OutlinedTextField(
                    value = librarySearchQuery, onValueChange = { librarySearchQuery = it },
                    modifier = Modifier.fillMaxWidth().padding(top = 18.dp), singleLine = true,
                    label = { Text("Search your entire library") },
                    placeholder = { Text("Books, chapters, paragraphs, evidence and notes") }
                )
                if (librarySearchQuery.isNotBlank()) {
                    Text("LIBRARY RESULTS · " + librarySearchResults.size, color = Gold, fontSize = 10.sp, letterSpacing = 2.sp, modifier = Modifier.padding(top = 12.dp, bottom = 6.dp))
                    librarySearchResults.take(12).forEach { hit ->
                        Card(modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp), colors = CardDefaults.cardColors(containerColor = Panel)) {
                            Column(Modifier.fillMaxWidth().padding(10.dp)) {
                                Text(hit.bookTitle + " · " + hit.chapterTitle, color = Gold, fontSize = 10.sp)
                                Text(hit.blockText.ifBlank { hit.note.orEmpty() }.take(180), color = Color.White, fontSize = 12.sp)
                                TextButton(onClick = { openStoredBook(hit.versionId, hit.blockId) }) { Text("Open matching paragraph", color = Gold) }
                            }
                        }
                    }
                    if (librarySearchResults.isEmpty()) Text("No matching material in your saved library.", color = Muted, fontSize = 11.sp)
                }
                if (libraryBooks.isNotEmpty()) {
                    Text("ON THIS DEVICE", color = Gold, fontSize = 10.sp, letterSpacing = 2.sp, modifier = Modifier.padding(top = 24.dp, bottom = 8.dp))
                    LazyColumn(Modifier.fillMaxWidth().weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(libraryBooks, key = { it.versionId }) { entry ->
                            Card(colors = CardDefaults.cardColors(containerColor = Panel)) {
                                Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                                    Column(Modifier.weight(1f)) {
                                        Text(entry.title, color = Color.White, fontWeight = FontWeight.SemiBold)
                                        Text("${entry.chapterCount} chapters · ${entry.sourceCount} sources", color = Muted, fontSize = 10.sp)
                                    }
                                    TextButton(onClick = { openStoredBook(entry.versionId) }) { Text("Open", color = Gold) }
                                    TextButton(onClick = {
                                        scope.launch {
                                            runCatching {
                                                withContext(Dispatchers.IO) {
                                                    libraryDatabase.withTransaction {
                                                        libraryDatabase.readerContent().deleteChapters(entry.versionId)
                                                        libraryDatabase.readerContent().deleteSources(entry.versionId)
                                                        libraryDatabase.annotations().deleteForVersion(entry.versionId)
                                                        libraryDatabase.progress().delete(entry.versionId)
                                                        libraryDatabase.libraryBooks().delete(entry.versionId)
                                                    }
                                                }
                                                runCatching {
                                                    context.contentResolver.releasePersistableUriPermission(
                                                        Uri.parse(entry.documentUri), Intent.FLAG_GRANT_READ_URI_PERMISSION
                                                    )
                                                }
                                                libraryBooks = libraryBooks.filterNot { it.versionId == entry.versionId }
                                            }.onFailure { error = "Could not remove this library entry." }
                                        }
                                    }) { Text("Remove", color = Muted) }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            Column(Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
                Text(current.title, color = Gold, fontWeight = FontWeight.Bold, fontSize = 18.sp)
                Text("${current.chapters.size} chapters · ${current.sources.size} sources", color = Muted, fontSize = 11.sp)
                error?.let { Text(it, color = Color(0xFFFF8C82), fontSize = 11.sp, modifier = Modifier.padding(top = 4.dp)) }
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box {
                        OutlinedButton(onClick = { sourceMenuExpanded = true }) {
                            Text(current.sources.firstOrNull { it.id == selectedSourceId }?.title ?: "Select exact source")
                        }
                        DropdownMenu(expanded = sourceMenuExpanded, onDismissRequest = { sourceMenuExpanded = false }) {
                            current.sources.forEach { source ->
                                DropdownMenuItem(
                                    text = { Text(source.title) },
                                    onClick = {
                                        sourceMenuExpanded = false
                                        selectedSourceId = source.id
                                        mediaUri = null
                                        mediaMime = null
                                        audioPlayer?.release(); audioPlayer = null; audioReady = false; audioPlaying = false; videoReady = false
                                        videoView?.stopPlayback(); videoView = null
                                        mediaStatus = "Selected ${source.title}. Attach only the matching local media file."
                                    }
                                )
                            }
                        }
                    }
                    OutlinedButton(
                        enabled = selectedSourceId != null,
                        onClick = { mediaPicker.launch(arrayOf("video/*", "audio/*")) }
                    ) { Text("Attach media") }
                }
                Text(mediaStatus, color = Muted, fontSize = 10.sp, modifier = Modifier.padding(top = 4.dp))
                val attachedUri = mediaUri
                if (attachedUri != null && mediaMime?.startsWith("video/") == true) {
                    AndroidView(
                        factory = { viewContext ->
                            VideoView(viewContext).also { view ->
                                view.tag = attachedUri.toString()
                                MediaController(viewContext).also { controller ->
                                    controller.setAnchorView(view)
                                    view.setMediaController(controller)
                                }
                                view.setOnPreparedListener {
                                    videoReady = true
                                    mediaStatus = "Video ready · selected source only."
                                }
                                view.setOnErrorListener { _, what, extra ->
                                    videoReady = false
                                    mediaStatus = "The selected video could not be played (error $what/$extra)."
                                    true
                                }
                                view.setOnCompletionListener {
                                    mediaStatus = "Video playback complete."
                                }
                                view.setVideoURI(attachedUri)
                                videoView = view
                            }
                        },
                        update = { view ->
                            if (view.tag != attachedUri.toString()) {
                                view.tag = attachedUri.toString()
                                view.setVideoURI(attachedUri)
                            }
                            videoView = view
                        },
                        modifier = Modifier.fillMaxWidth().height(210.dp)
                    )
                }
                if (attachedUri != null && mediaMime?.startsWith("audio/") == true) {
                    Button(
                        enabled = audioReady,
                        onClick = {
                            audioPlayer?.let { player ->
                                if (player.isPlaying) { player.pause(); audioPlaying = false }
                                else { player.start(); audioPlaying = true }
                            }
                        },
                        modifier = Modifier.padding(top = 6.dp)
                    ) { Text(if (audioPlaying) "Pause audio" else "Play audio") }
                }
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = query, onValueChange = { query = it }, modifier = Modifier.fillMaxWidth(),
                    singleLine = true, label = { Text("Search all chapters and notes") }
                )
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    TextButton(onClick = { showBookmarksOnly = !showBookmarksOnly }) {
                        Text(if (showBookmarksOnly) "Show all blocks" else "★ Bookmarks (${bookmarkedBlocks.size})", color = Gold)
                    }
                }
                Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { chapterIndex = (chapterIndex - 1).coerceAtLeast(0) }, enabled = chapterIndex > 0) { Text("Previous") }
                    OutlinedButton(onClick = { chapterIndex = (chapterIndex + 1).coerceAtMost(current.chapters.lastIndex) }, enabled = chapterIndex < current.chapters.lastIndex) { Text("Next") }
                }
                Text("CHAPTER ${chapterIndex + 1} / ${current.chapters.size}", color = Gold, fontSize = 10.sp, letterSpacing = 2.sp, modifier = Modifier.padding(top = 12.dp))
                Text(current.chapters[chapterIndex].title, fontSize = 25.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(vertical = 8.dp))
            }
            val blocks: List<Triple<Int, String, Block>> = if (query.isBlank() && !showBookmarksOnly) {
                current.chapters[chapterIndex].blocks.map { Triple(chapterIndex, current.chapters[chapterIndex].title, it) }
            } else {
                current.chapters.flatMapIndexed { index, chapter ->
                    chapter.blocks.filter { block ->
                        val matchesQuery = query.isBlank() ||
                            block.text.contains(query, true) ||
                            notesByBlock[block.id]?.contains(query, true) == true ||
                            block.evidence.any { it.excerpt.contains(query, true) || it.source.contains(query, true) }
                        matchesQuery && (!showBookmarksOnly || block.id in bookmarkedBlocks)
                    }.map { Triple(index, chapter.title, it) }
                }
            }
            LaunchedEffect(current.versionId, chapterIndex, query, showBookmarksOnly) {
                if (query.isBlank() && !showBookmarksOnly) {
                    val target = resumeBlockId?.let { id -> blocks.indexOfFirst { it.third.id == id } } ?: 0
                    readerListState.scrollToItem(target.coerceIn(0, (blocks.size - 1).coerceAtLeast(0)))
                    resumeBlockId = null
                }
            }
            LaunchedEffect(current.versionId, chapterIndex, query, showBookmarksOnly) {
                if (query.isBlank() && !showBookmarksOnly) {
                    snapshotFlow { readerListState.firstVisibleItemIndex }.distinctUntilChanged().collect { visibleIndex ->
                        blocks.getOrNull(visibleIndex)?.third?.let { visibleBlock ->
                            runCatching {
                                withContext(Dispatchers.IO) {
                                    libraryDatabase.progress().upsert(
                                        ReaderProgressEntity(current.versionId, chapterIndex, visibleBlock.id, System.currentTimeMillis())
                                    )
                                }
                            }.onFailure { error = "Could not save paragraph-level reading progress." }
                        }
                    }
                }
            }
            LazyColumn(
                state = readerListState,
                modifier = Modifier.weight(1f).fillMaxWidth().padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                items(blocks, key = { it.third.id }) { (resultChapterIndex, chapterTitle, block) ->
                    Card(colors = CardDefaults.cardColors(containerColor = Panel), shape = RoundedCornerShape(12.dp)) {
                        Column(Modifier.fillMaxWidth().padding(16.dp)) {
                            if (query.isNotBlank() || showBookmarksOnly) {
                                Text(chapterTitle, color = Gold, fontSize = 10.sp, fontWeight = FontWeight.Bold)
                                TextButton(onClick = {
                                    chapterIndex = resultChapterIndex
                                    query = ""
                                }) { Text("Open chapter", color = Gold) }
                            }
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                                Text(block.type.replace('_', ' '), color = Gold, fontSize = 10.sp, letterSpacing = 1.sp)
                                TextButton(onClick = {
                                    val next = block.id !in bookmarkedBlocks
                                    scope.launch {
                                        runCatching {
                                            withContext(Dispatchers.IO) {
                                                val previous = libraryDatabase.annotations().find(current.versionId, block.id)
                                                libraryDatabase.annotations().upsert(
                                                    ReaderAnnotationEntity(current.versionId, block.id, previous?.note, next, System.currentTimeMillis())
                                                )
                                            }
                                            bookmarkedBlocks = if (next) bookmarkedBlocks + block.id else bookmarkedBlocks - block.id
                                        }.onFailure { error = "Could not save bookmark to the on-device library." }
                                    }
                                }) { Text(if (block.id in bookmarkedBlocks) "★ Saved" else "☆ Bookmark", color = Gold) }
                            }
                            Text(block.text, fontSize = 15.sp, lineHeight = 23.sp, modifier = Modifier.padding(top = 7.dp))
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                TextButton(onClick = {
                                    editingBlockId = block.id
                                    noteDraft = notesByBlock[block.id].orEmpty()
                                }) { Text(if (notesByBlock[block.id].isNullOrBlank()) "Add note" else "Edit note", color = Gold) }
                                if (!notesByBlock[block.id].isNullOrBlank()) {
                                    Text("NOTE SAVED", color = Muted, fontSize = 9.sp)
                                }
                            }
                            notesByBlock[block.id]?.takeIf { it.isNotBlank() }?.let {
                                Text(it, color = Muted, fontSize = 12.sp, lineHeight = 18.sp)
                            }
                            Text("PROVENANCE · ${block.provenance}", color = Muted, fontSize = 9.sp, modifier = Modifier.padding(top = 8.dp))
                            block.evidence.forEach { evidence ->
                                HorizontalDivider(color = Color(0xFF343945), modifier = Modifier.padding(vertical = 8.dp))
                                Text("${evidence.source} · ${evidence.locator}", color = Gold, fontSize = 11.sp)
                                if (evidence.startMs != null) {
                                    val canSeek = mediaUri != null && selectedSourceId == evidence.sourceId &&
                                        (mediaMime?.startsWith("video/") == true && videoReady || audioReady)
                                    OutlinedButton(
                                        enabled = canSeek,
                                        onClick = {
                                            val position = evidence.startMs.coerceIn(0, Int.MAX_VALUE.toLong()).toInt()
                                            if (mediaMime?.startsWith("video/") == true) {
                                                videoView?.seekTo(position)
                                                videoView?.start()
                                            } else {
                                                audioPlayer?.let { player ->
                                                    player.seekTo(position)
                                                    if (!player.isPlaying) player.start()
                                                    audioPlaying = true
                                                }
                                            }
                                        },
                                        modifier = Modifier.padding(top = 4.dp)
                                    ) { Text("Jump to ${evidence.locator}") }
                                }
                                if (evidence.excerpt.isNotBlank()) Text(evidence.excerpt, color = Muted, fontSize = 11.sp, lineHeight = 17.sp)
                            }
                        }
                    }
                }
                if (blocks.isEmpty()) item { Text(if (showBookmarksOnly) "No bookmarked blocks match this view." else "No matching blocks in this textbook.", color = Muted) }
            }
        }
        if (showStudy) {
            current?.let { activeBook ->
                StudyPracticeDialog(
                    book = activeBook,
                    database = libraryDatabase,
                    onDismiss = { showStudy = false }
                )
            }
        }
        editingBlockId?.let { blockId ->
            AlertDialog(
                onDismissRequest = { editingBlockId = null },
                title = { Text("Your private note") },
                text = {
                    OutlinedTextField(
                        value = noteDraft,
                        onValueChange = { if (it.length <= 5000) noteDraft = it },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 3,
                        maxLines = 8,
                        label = { Text("Note · up to 5,000 characters") }
                    )
                },
                confirmButton = {
                    TextButton(onClick = {
                        val currentBook = book
                        if (currentBook != null) {
                            val saved = noteDraft.trim()
                            scope.launch {
                                runCatching {
                                    withContext(Dispatchers.IO) {
                                        val previous = libraryDatabase.annotations().find(currentBook.versionId, blockId)
                                        libraryDatabase.annotations().upsert(
                                            ReaderAnnotationEntity(currentBook.versionId, blockId,
                                                saved.takeIf { it.isNotBlank() },
                                                previous?.bookmarked ?: (blockId in bookmarkedBlocks),
                                                System.currentTimeMillis())
                                        )
                                    }
                                    notesByBlock = if (saved.isBlank()) notesByBlock - blockId else notesByBlock + (blockId to saved)
                            editingBlockId = null
                                }.onFailure { error = "Could not save local note." }
                            }
                        }
                    }) { Text("Save note") }
                },
                dismissButton = {
                    TextButton(onClick = { editingBlockId = null }) { Text("Cancel") }
                },
                containerColor = Panel
            )
        }
    }
}
