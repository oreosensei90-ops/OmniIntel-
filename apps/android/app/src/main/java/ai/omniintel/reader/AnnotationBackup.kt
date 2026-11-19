package ai.omniintel.reader

import org.json.JSONArray
import org.json.JSONObject

private const val ANNOTATION_BACKUP_SCHEMA = 1
private const val MAX_ANNOTATION_BACKUP_RECORDS = 100_000

fun annotationBackupJson(items: List<ReaderAnnotationEntity>): String {
    require(items.size <= MAX_ANNOTATION_BACKUP_RECORDS) { "Annotation backup exceeds the 100,000-record limit." }
    val rows = JSONArray()
    items.forEach { item ->
        rows.put(JSONObject()
            .put("version_id", item.versionId)
            .put("block_id", item.blockId)
            .put("note", item.note)
            .put("bookmarked", item.bookmarked)
            .put("updated_at_epoch_ms", item.updatedAtEpochMs))
    }
    return JSONObject()
        .put("schema_version", ANNOTATION_BACKUP_SCHEMA)
        .put("backup_type", "OMNIINTEL_READER_ANNOTATIONS")
        .put("exported_at_epoch_ms", System.currentTimeMillis())
        .put("records", rows)
        .toString(2)
}

fun parseAnnotationBackup(raw: String): List<ReaderAnnotationEntity> {
    require(raw.length <= 5 * 1024 * 1024) { "Annotation backup exceeds 5 MiB." }
    val root = JSONObject(raw)
    require(root.optInt("schema_version", -1) == ANNOTATION_BACKUP_SCHEMA) { "Unsupported annotation backup schema." }
    require(root.optString("backup_type") == "OMNIINTEL_READER_ANNOTATIONS") { "This is not an OmniIntel annotation backup." }
    val rows = root.optJSONArray("records") ?: error("Annotation backup has no records array.")
    require(rows.length() <= MAX_ANNOTATION_BACKUP_RECORDS) { "Annotation backup exceeds the 100,000-record limit." }
    val seen = mutableSetOf<Pair<String, String>>()
    return (0 until rows.length()).map { index ->
        val row = rows.getJSONObject(index)
        val versionId = row.optString("version_id")
        val blockId = row.optString("block_id")
        require(versionId.isNotBlank() && versionId.length <= 128) { "Invalid textbook version ID." }
        require(blockId.isNotBlank() && blockId.length <= 128) { "Invalid textbook block ID." }
        require(seen.add(versionId to blockId)) { "Duplicate annotation record." }
        val note = if (row.isNull("note")) null else row.optString("note")
        require(note == null || note.length <= 12_000) { "Annotation note exceeds 12,000 characters." }
        ReaderAnnotationEntity(
            versionId, blockId, note, row.optBoolean("bookmarked", false),
            row.optLong("updated_at_epoch_ms").also { require(it >= 0) { "Invalid annotation timestamp." } }
        )
    }
}
