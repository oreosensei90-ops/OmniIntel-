package ai.omniintel.reader

import android.content.Context
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
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext
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

data class ReaderSource(val id: String, val title: String)
data class Evidence(val sourceId: String, val source: String, val locator: String, val startMs: Long?, val excerpt: String)
data class Block(val id: String, val type: String, val text: String, val provenance: String, val evidence: List<Evidence>)
data class Book(val title: String, val versionId: String, val sources: List<ReaderSource>, val chapters: List<ReaderChapter>)
data class ReaderChapter(val title: String, val blocks: List<Block>)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(
                primary = Gold, onPrimary = Ink, background = Ink, surface = Panel,
                onBackground = Color(0xFFF1F2F4), onSurface = Color(0xFFF1F2F4)
            )) {
                Surface(Modifier.fillMaxSize(), color = Ink) {
                    ReaderScreen { uri, callback ->
                        lifecycleScope.launch {
                            callback(withContext(Dispatchers.IO) { runCatching { parse(uri) } })
                        }
                    }
                }
            }
        }
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
            require(sourceId.isNotBlank() && !sourcesById.containsKey(sourceId)) {
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
                Block(
                    stableId,
                    blockType,
                    text,
                    block.optString("provenance", "UNSPECIFIED"),
                    evidence
                )
            }
            ReaderChapter(chapter.optString("title", "Chapter ${i + 1}"), blocks)
        }
        require(chapters.isNotEmpty()) { "This textbook has no readable chapters." }
        return Book(version.optString("textbook_title", version.optString("title", "Course textbook")), versionId, sourcesById.values.toList(), chapters)
    }
}

@Composable
private fun ReaderScreen(open: (Uri, (Result<Book>) -> Unit) -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val scope = rememberCoroutineScope()
    var book by remember { mutableStateOf<Book?>(null) }
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
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) open(uri) { result ->
            result.onSuccess { loadedBook ->
                scope.launch {
                    val progressKey = intPreferencesKey("chapter:${loadedBook.versionId}")
                    val savedChapter = runCatching {
                        context.readerProgressStore.data.first()[progressKey]
                    }.getOrNull() ?: 0
                    book = loadedBook
                    chapterIndex = savedChapter.coerceIn(0, loadedBook.chapters.lastIndex)
                    query = ""
                    showBookmarksOnly = false
                    error = null
                    selectedSourceId = null; mediaUri = null; mediaMime = null
                    audioPlayer?.release(); audioPlayer = null; audioReady = false; audioPlaying = false; videoReady = false
                    videoView?.stopPlayback(); videoView = null
                    mediaStatus = "Select the exact course source, then attach only the matching local media file."
                }
            }.onFailure { error = it.message ?: "Could not open reader export." }
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
            val preferences = context.readerProgressStore.data.first()
            val prefix = "${currentBook.versionId}:"
            notesByBlock = preferences.asMap().mapNotNull { (key, value) ->
                val name = key.name
                if (name.startsWith("note:$prefix") && value is String) name.removePrefix("note:$prefix") to value else null
            }.toMap()
            bookmarkedBlocks = preferences.asMap().mapNotNull { (key, value) ->
                val name = key.name
                if (name.startsWith("bookmark:$prefix") && value == true) name.removePrefix("bookmark:$prefix") else null
            }.toSet()
        }.onFailure { error = "Could not restore local notes and bookmarks." }
    }
    LaunchedEffect(book?.versionId, chapterIndex) {
        val currentBook = book ?: return@LaunchedEffect
        val progressKey = intPreferencesKey("chapter:${currentBook.versionId}")
        runCatching {
            context.readerProgressStore.edit { preferences ->
                preferences[progressKey] = chapterIndex
            }
        }
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
                Text("OFFLINE READER", color = Gold, fontSize = 10.sp, letterSpacing = 2.sp)
            }
            OutlinedButton(onClick = { picker.launch(arrayOf("application/json")) }) {
                Text(if (book == null) "Open textbook" else "Open another")
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
                error?.let { Text(it, color = Color(0xFFFF8C82), modifier = Modifier.padding(top = 12.dp)) }
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
            LazyColumn(
                Modifier.weight(1f).fillMaxWidth().padding(horizontal = 16.dp),
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
                                    val key = booleanPreferencesKey("bookmark:${current.versionId}:${block.id}")
                                    val next = block.id !in bookmarkedBlocks
                                    scope.launch {
                                        runCatching {
                                            context.readerProgressStore.edit { prefs -> prefs[key] = next }
                                            bookmarkedBlocks = if (next) bookmarkedBlocks + block.id else bookmarkedBlocks - block.id
                                        }.onFailure { error = "Could not save bookmark." }
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
                            val key = stringPreferencesKey("note:${currentBook.versionId}:$blockId")
                            val saved = noteDraft.trim()
                            scope.launch {
                                runCatching {
                                    context.readerProgressStore.edit { prefs ->
                                        if (saved.isBlank()) prefs.remove(key) else prefs[key] = saved
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
