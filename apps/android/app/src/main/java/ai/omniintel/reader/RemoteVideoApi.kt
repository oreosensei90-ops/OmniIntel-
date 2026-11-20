package ai.omniintel.reader

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import java.io.File
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

private fun remoteApiBase(raw: String): String {
    val value = raw.trim().trimEnd('/')
    val url = URL(value)
    val local = url.host == "localhost" || url.host == "127.0.0.1"
    require(url.protocol == "https" || (local && url.protocol == "http")) {
        "Use HTTPS for a remote OmniIntel API. HTTP is allowed only for localhost."
    }
    require(url.userInfo == null && url.query == null && url.ref == null) {
        "API address must be an origin only, without credentials, query or fragment."
    }
    return value
}

private fun remoteApiRequest(
    base: String, token: String, path: String, method: String,
    payload: JSONObject? = null
): JSONObject {
    val connection = URL(remoteApiBase(base) + path).openConnection() as HttpURLConnection
    connection.requestMethod = method
    connection.connectTimeout = 20_000
    connection.readTimeout = 120_000
    connection.instanceFollowRedirects = false
    connection.setRequestProperty("Authorization", "Bearer $token")
    connection.setRequestProperty("Accept", "application/json")
    if (payload != null) {
        connection.doOutput = true
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
        connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
    }
    try {
        val status = connection.responseCode
        val stream = if (status in 200..299) connection.inputStream else connection.errorStream
        val raw = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
        val result = runCatching { JSONObject(raw) }.getOrElse {
            error("OmniIntel API returned an invalid response (HTTP $status).")
        }
        if (status !in 200..299) error(result.optString("error").ifBlank {
            result.optString("detail").ifBlank { "OmniIntel API request failed (HTTP $status)." }
        })
        return result
    } finally {
        connection.disconnect()
    }
}

fun submitRemoteVideoJob(
    apiBase: String, token: String, videoUrl: String, language: String? = null,
    approveAi: Boolean = false
): JSONObject {
    require(token.isNotBlank()) { "Enter the API access token." }
    val payload = JSONObject()
        .put("url", videoUrl)
        .put("approve_network", true)
        .put("approve_ai", approveAi)
        .put("chapter_minutes", 10)
    if (!language.isNullOrBlank()) payload.put("language", language)
    return remoteApiRequest(apiBase, token, "/v1/youtube/jobs", "POST", payload)
}

fun getRemoteVideoJob(apiBase: String, token: String, statusPath: String): JSONObject {
    require(statusPath.startsWith("/v1/jobs/") && !statusPath.contains("://")) {
        "The server returned an invalid job status path."
    }
    return remoteApiRequest(apiBase, token, statusPath, "GET")
}

fun downloadRemoteReaderJson(resultUrl: String): String {
    val url = URL(resultUrl)
    require(url.protocol == "https" && url.host.isNotBlank()) {
        "The server returned an invalid reader download URL."
    }
    val connection = url.openConnection() as HttpURLConnection
    connection.requestMethod = "GET"
    connection.connectTimeout = 20_000
    connection.readTimeout = 120_000
    connection.instanceFollowRedirects = false
    try {
        val status = connection.responseCode
        if (status !in 200..299) error("Reader download failed (HTTP $status).")
        val text = connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        require(text.toByteArray(Charsets.UTF_8).size <= 20 * 1024 * 1024) {
            "Reader export exceeds the 20 MiB download limit."
        }
        JSONObject(text) // fail closed before handing the export to the importer
        return text
    } finally {
        connection.disconnect()
    }
}

fun uploadRemoteMedia(
    context: Context, apiBase: String, token: String, uri: Uri,
    language: String? = null, approveAi: Boolean = false
): JSONObject {
    require(token.isNotBlank()) { "Enter the API access token." }
    val mime = context.contentResolver.getType(uri).orEmpty().lowercase()
    require(mime.startsWith("audio/") || mime.startsWith("video/")) {
        "Choose a supported audio or video file."
    }
    var displayName = "omniintel-media-upload"
    var declaredSize = -1L
    context.contentResolver.query(
        uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null
    )?.use { cursor ->
        if (cursor.moveToFirst()) {
            val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
            if (nameIndex >= 0) displayName = cursor.getString(nameIndex) ?: displayName
            if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) declaredSize = cursor.getLong(sizeIndex)
        }
    }
    val maxBytes = 250L * 1024L * 1024L
    require(declaredSize <= maxBytes || declaredSize < 0) {
        "Media upload exceeds the 250 MiB limit."
    }
    val safeName = displayName.replace("\"", "").replace("\r", "").replace("\n", "").take(180)
    val payload = JSONObject()
        .put("filename", safeName)
        .put("title", safeName)
        .put("approve_media_upload", true)
        .put("approve_ai", approveAi)
        .put("chapter_minutes", 10)
    if (!language.isNullOrBlank()) payload.put("language", language)
    val created = remoteApiRequest(apiBase, token, "/v1/media/jobs", "POST", payload)
    val uploadUrl = created.optString("upload_url")
    val completePath = created.optString("upload_complete_url")
    require(uploadUrl.startsWith("https://") && completePath.startsWith("/v1/jobs/")) {
        "The Worker did not return valid upload instructions."
    }
    val staged = File.createTempFile("omniintel-upload-", ".tmp", context.cacheDir)
    try {
        val input = context.contentResolver.openInputStream(uri)
            ?: error("Could not open the selected media file.")
        var total = 0L
        input.use { stream ->
            staged.outputStream().use { output ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val count = stream.read(buffer)
                    if (count < 0) break
                    total += count
                    require(total <= maxBytes) { "Media upload exceeds the 250 MiB limit." }
                    output.write(buffer, 0, count)
                }
            }
        }
        require(total > 0) { "The selected media file is empty." }
        val upload = URL(uploadUrl).openConnection() as HttpURLConnection
        upload.requestMethod = "PUT"
        upload.connectTimeout = 20_000
        upload.readTimeout = 180_000
        upload.instanceFollowRedirects = false
        upload.doOutput = true
        upload.setFixedLengthStreamingMode(staged.length())
        upload.setRequestProperty("Content-Type", mime)
        try {
            upload.outputStream.use { output ->
                staged.inputStream().use { source -> source.copyTo(output, 64 * 1024) }
            }
            val status = upload.responseCode
            if (status !in 200..299) error("Backblaze upload failed (HTTP $status).")
        } finally {
            upload.disconnect()
        }
    } finally {
        staged.delete()
    }
    remoteApiRequest(apiBase, token, completePath, "POST", JSONObject())
    return created
}
