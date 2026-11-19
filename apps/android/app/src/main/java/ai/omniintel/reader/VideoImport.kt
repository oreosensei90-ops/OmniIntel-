package ai.omniintel.reader

import android.content.Intent
import android.net.Uri

data class ParsedYouTubeVideo(
    val videoId: String,
    val url: String
)

fun parseYouTubeUrl(raw: String): ParsedYouTubeVideo? {
    val candidate = Regex("""https?://[^\s<>"']+""")
        .find(raw.trim())?.value
        ?.trimEnd('.', ',', ')', ']', '}', '!', '?', ';')
        ?: return null

    val uri = runCatching { Uri.parse(candidate) }.getOrNull() ?: return null
    val host = uri.host?.lowercase() ?: return null
    val allowed = setOf(
        "youtube.com", "www.youtube.com", "m.youtube.com",
        "music.youtube.com", "youtu.be", "www.youtu.be"
    )
    if (uri.scheme !in setOf("http", "https") ||
        host !in allowed || uri.userInfo != null ||
        (uri.port != -1 && uri.port != 80 && uri.port != 443)
    ) return null

    val id = when (host) {
        "youtu.be", "www.youtu.be" -> uri.pathSegments.firstOrNull()
        else -> when {
            uri.path == "/watch" -> uri.getQueryParameter("v")
            else -> {
                val parts = uri.pathSegments
                if (parts.size >= 2 &&
                    parts.first() in setOf("shorts", "live", "embed")
                ) parts[1] else null
            }
        }
    }?.takeIf { it.matches(Regex("[A-Za-z0-9_-]{6,20}")) } ?: return null

    return ParsedYouTubeVideo(id, "https://www.youtube.com/watch?v=$id")
}

fun extractYouTubeUrl(intent: Intent?): String? {
    if (intent == null) return null
    val candidates = mutableListOf<String>()

    intent.dataString?.let(candidates::add)
    intent.getStringExtra(Intent.EXTRA_TEXT)?.let(candidates::add)
    intent.clipData?.let { clip ->
        for (i in 0 until clip.itemCount) {
            val item = clip.getItemAt(i)
            item.text?.toString()?.let(candidates::add)
            item.uri?.toString()?.let(candidates::add)
        }
    }

    return candidates.firstNotNullOfOrNull { parseYouTubeUrl(it)?.url }
}
