package ai.omniintel.reader

import org.json.JSONArray
import org.json.JSONObject

/** Portable queue contract for explicit handoff to the local Python engine. */
fun videoQueueJson(items: List<VideoImportEntity>): String {
    require(items.size <= 200) { "Video queue exceeds the 200-item export limit." }
    val rows = JSONArray()
    items.forEach { item ->
        rows.put(
            JSONObject()
                .put("video_id", item.videoId)
                .put("url", item.url)
                .put("created_at_epoch_ms", item.createdAtEpochMs)
                .put("status", item.status)
        )
    }
    return JSONObject()
        .put("schema_version", 1)
        .put("queue_type", "OMNIINTEL_YOUTUBE_QUEUE")
        .put("exported_at_epoch_ms", System.currentTimeMillis())
        .put("items", rows)
        .toString(2)
}
