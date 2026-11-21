package ai.omniintel.reader

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.room.withTransaction
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.math.max

private data class NativeStudyCard(
    val blockId: String,
    val front: String,
    val back: String,
    val kind: String,
    val chapter: String,
    val evidence: List<Evidence>
)

@Composable
fun StudyPracticeDialog(
    book: Book,
    database: ReaderDatabase,
    onDismiss: () -> Unit
) {
    val cards = remember(book.versionId, book.chapters) {
        book.chapters.flatMap { chapter ->
            chapter.blocks.mapNotNull { block ->
                val kind = block.type.uppercase()
                if (kind !in setOf("DEFINITION", "EXERCISE", "FLASHCARD", "QUESTION")) return@mapNotNull null
                val front = block.studyFront.trim()
                if (front.isBlank()) return@mapNotNull null
                val answer = block.studyBack.trim().ifBlank {
                    block.evidence.map { it.excerpt.trim() }.filter { it.isNotBlank() }
                        .distinct().joinToString("\n\n")
                        .ifBlank { "No answer is supplied. Recall the idea, then review the source evidence." }
                }
                NativeStudyCard(block.id, front, answer, kind, chapter.title, block.evidence)
            }
        }
    }
    var progress by remember(book.versionId) { mutableStateOf<Map<String, StudyProgressEntity>>(emptyMap()) }
    var showAll by remember { mutableStateOf(false) }
    var index by remember { mutableStateOf(0) }
    var revealed by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(book.versionId) {
        progress = withContext(Dispatchers.IO) {
            database.studyProgress().forVersion(book.versionId).associateBy { it.blockId }
        }
    }

    val now = System.currentTimeMillis()
    val dueCards = remember(cards, progress, showAll, now) {
        if (showAll) cards else cards.filter { (progress[it.blockId]?.dueAtEpochMs ?: 0L) <= now }
    }
    val current = dueCards.getOrNull(index)

    var pendingReview by remember { mutableStateOf<StudyProgressEntity?>(null) }

    fun review(rating: String) {
        val card = current ?: return
        if (saving) return
        saving = true
        message = null
        val old = progress[card.blockId]
        val oldEase = (old?.easeFactor ?: 2.5).coerceIn(1.3, 3.0)
        val oldInterval = old?.intervalDays ?: 0.0
        val oldRepetitions = old?.repetitions ?: 0
        val nextEase = when (rating) {
            "AGAIN" -> max(1.3, oldEase - 0.2)
            "HARD" -> max(1.3, oldEase - 0.15)
            "EASY" -> (oldEase + 0.15).coerceAtMost(3.0)
            else -> oldEase
        }
        val nextRepetitions: Int
        val nextInterval: Double
        when (rating) {
            "AGAIN" -> { nextRepetitions = 0; nextInterval = 10.0 / 1440.0 }
            "HARD" -> {
                nextRepetitions = oldRepetitions + 1
                nextInterval = if (oldRepetitions == 0) 1.0 else max(1.0, oldInterval * 1.2)
            }
            "EASY" -> {
                nextRepetitions = oldRepetitions + 1
                nextInterval = if (oldRepetitions == 0) 4.0 else oldInterval * oldEase * 1.3
            }
            else -> {
                nextRepetitions = oldRepetitions + 1
                nextInterval = when (oldRepetitions) {
                    0 -> 1.0
                    1 -> 3.0
                    else -> oldInterval * oldEase
                }
            }
        }
        val reviewedAt = System.currentTimeMillis()
        val updated = StudyProgressEntity(
            versionId = book.versionId,
            blockId = card.blockId,
            repetitions = nextRepetitions,
            intervalDays = nextInterval,
            easeFactor = nextEase,
            dueAtEpochMs = reviewedAt + (nextInterval * 86_400_000.0).toLong(),
            lastReviewedAtEpochMs = reviewedAt
        )
        // Persist the rating off the UI thread; advance only after the write succeeds.
        message = "Saving review…"
        pendingReview = updated
    }

    LaunchedEffect(pendingReview) {
        val item = pendingReview ?: return@LaunchedEffect
        runCatching {
            withContext(Dispatchers.IO) {
                database.withTransaction { database.studyProgress().upsert(item) }
            }
        }.onSuccess {
            progress = progress + (item.blockId to item)
            // In due-only mode the just-reviewed card leaves the queue, so keep the
            // same index; in all-cards mode advance to the next card.
            if (showAll) index = (index + 1).coerceAtMost(dueCards.size)
            revealed = false
            message = null
        }.onFailure {
            message = "Could not save this review. Your previous schedule is unchanged."
        }
        saving = false
        pendingReview = null
    }

    Dialog(onDismissRequest = onDismiss) {
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = Color(0xFF1B1F27))
        ) {
            Column(
                modifier = Modifier.fillMaxWidth().padding(20.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("ACTIVE RECALL", color = Color(0xFFE2BD71), fontSize = 11.sp, fontWeight = FontWeight.Bold)
                    TextButton(onClick = onDismiss) { Text("Close", color = Color(0xFFE2BD71)) }
                }
                Text(book.title, color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                Text(
                    "${cards.size} cards · ${cards.count { (progress[it.blockId]?.dueAtEpochMs ?: 0L) <= System.currentTimeMillis() }} due · ${progress.size} reviewed",
                    color = Color(0xFF9BA3B2), fontSize = 11.sp
                )
                if (cards.isEmpty()) {
                    Text("No definitions, exercises, questions or flashcards are available in this textbook yet.", color = Color.White)
                } else if (current == null) {
                    Text(if (dueCards.isEmpty()) "You're all caught up. No cards are due right now." else "Study session complete.", color = Color.White, fontSize = 19.sp, fontWeight = FontWeight.Bold)
                    Text("Your ratings are saved on this device and determine when each card returns.", color = Color(0xFF9BA3B2))
                    if (!showAll && cards.isNotEmpty()) {
                        OutlinedButton(onClick = { showAll = true; index = 0; revealed = false }) {
                            Text("Study all cards")
                        }
                    }
                } else {
                    Text("${index + 1} / ${dueCards.size} · ${current.kind} · ${current.chapter}", color = Color(0xFFE2BD71), fontSize = 10.sp)
                    Card(colors = CardDefaults.cardColors(containerColor = Color(0xFF111318))) {
                        Column(Modifier.fillMaxWidth().padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            Text(current.front, color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
                            if (revealed) {
                                androidx.compose.material3.HorizontalDivider(color = Color(0xFF343945))
                                Text(current.back, color = Color(0xFFE7E9EE), fontSize = 15.sp, lineHeight = 22.sp)
                                current.evidence.forEach { evidence ->
                                    Text("${evidence.source} · ${evidence.locator}", color = Color(0xFFE2BD71), fontSize = 10.sp)
                                    if (evidence.excerpt.isNotBlank()) Text(evidence.excerpt, color = Color(0xFF9BA3B2), fontSize = 11.sp)
                                }
                            }
                        }
                    }
                    if (!revealed) {
                        Button(onClick = { revealed = true }, modifier = Modifier.fillMaxWidth()) { Text("Reveal answer") }
                    } else {
                        Text("How well did you recall it?", color = Color(0xFF9BA3B2), fontSize = 12.sp)
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            OutlinedButton(enabled = !saving, onClick = { review("AGAIN") }, modifier = Modifier.weight(1f)) { Text("Again") }
                            OutlinedButton(enabled = !saving, onClick = { review("HARD") }, modifier = Modifier.weight(1f)) { Text("Hard") }
                        }
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Button(enabled = !saving, onClick = { review("GOOD") }, modifier = Modifier.weight(1f)) { Text("Good") }
                            Button(enabled = !saving, onClick = { review("EASY") }, modifier = Modifier.weight(1f)) { Text("Easy") }
                        }
                    }
                }
                message?.let { Text(it, color = Color(0xFFE2BD71), fontSize = 11.sp) }
            }
        }
    }
}
