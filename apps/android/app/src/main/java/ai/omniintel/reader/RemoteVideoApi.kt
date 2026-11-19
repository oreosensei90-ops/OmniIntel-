package ai.omniintel.reader

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
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
    base: String,
    token: String,
    path: String,
    method: String,
    payload: JSONObject? = null
): JSONObject {
    val endpoint = URL(remoteApiBase(base) + path)
    val connection = endpoint.openConnection() as HttpURLConnection
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
        if (status !in 200..299) {
            error(result.optString("detail").ifBlank { "OmniIntel API request failed (HTTP $status)." })
        }
        return result
    } finally {
        connection.disconnect()
    }
}

fun submitRemoteVideoJob(
    apiBase: String,
    token: String,
    videoUrl: String,
    language: String? = null
): JSONObject {
    require(token.isNotBlank()) { "Enter the API access token." }
    val payload = JSONObject()
        .put("url", videoUrl)
        .put("approve_network", true)
        .put("approve_ai", true)
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


fun uploadRemoteMedia(
    context: Context,
    apiBase: String,
    token: String,
    uri: Uri,
    language: String? = null
): JSONObject {
    require(token.isNotBlank()) { "Enter the API access token." }
    val mime = context.contentResolver.getType(uri).orEmpty().lowercase()
    require(mime.startsWith("audio/") || mime.startsWith("video/")) {
        "Choose a supported audio or video file."
    }
    var displayName = "omniintel-media-upload"
    var declaredSize = -1L
    context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)
        ?.use { cursor ->
            if (cursor.moveToFirst()) {
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                if (nameIndex >= 0) displayName = cursor.getString(nameIndex) ?: displayName
                if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) declaredSize = cursor.getLong(sizeIndex)
            }
        }
    val maxBytes = 250L * 1024L * 1024L
    require(declaredSize <= maxBytes || declaredSize < 0) { "Media upload exceeds the 250 MiB limit." }
    val safeName = displayName.replace("\"", "").replace("\r", "").replace("\n", "").take(180)
    val boundary = "----OmniIntel" + UUID.randomUUID().toString().replace("-", "")
    val connection = URL(remoteApiBase(apiBase) + "/v1/media/jobs").openConnection() as HttpURLConnection
    connection.requestMethod = "POST"
    connection.connectTimeout = 20_000
    connection.readTimeout = 120_000
    connection.instanceFollowRedirects = false
    connection.doOutput = true
    connection.setChunkedStreamingMode(64 * 1024)
    connection.setRequestProperty("Authorization", "Bearer $token")
    connection.setRequestProperty("Accept", "application/json")
    connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
    try {
        connection.outputStream.use { output ->
            fun writeField(name: String, value: String) {
                output.write("--$boundary\r\n".toByteArray(Charsets.UTF_8))
                output.write("Content-Disposition: form-data; name=\"$name\"\r\n\r\n".toByteArray(Charsets.UTF_8))
                output.write(value.toByteArray(Charsets.UTF_8))
                output.write("\r\n".toByteArray(Charsets.UTF_8))
            }
            output.write("--$boundary\r\n".toByteArray(Charsets.UTF_8))
            output.write("Content-Disposition: form-data; name=\"file\"; filename=\"$safeName\"\r\n".toByteArray(Charsets.UTF_8))
            output.write("Content-Type: $mime\r\n\r\n".toByteArray(Charsets.UTF_8))
            val input = context.contentResolver.openInputStream(uri)
                ?: error("Could not open the selected media file.")
            var total = 0L
            input.use { stream ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val count = stream.read(buffer)
                    if (count < 0) break
                    total += count
                    require(total <= maxBytes) { "Media upload exceeds the 250 MiB limit." }
                    output.write(buffer, 0, count)
                }
            }
            require(total > 0) { "The selected media file is empty." }
            output.write("\r\n".toByteArray(Charsets.UTF_8))
            writeField("approve_ai", "true")
            if (!language.isNullOrBlank()) writeField("language", language)
            writeField("title", safeName)
            output.write("--$boundary--\r\n".toByteArray(Charsets.UTF_8))
            output.flush()
        }
        val status = connection.responseCode
        val stream = if (status in 200..299) connection.inputStream else connection.errorStream
        val raw = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
        val result = runCatching { JSONObject(raw) }.getOrElse {
            error("OmniIntel API returned an invalid response (HTTP $status).")
        }
        if (status !in 200..299) {
            error(result.optString("detail").ifBlank { "Media upload failed (HTTP $status)." })
        }
        return result
    } finally {
        connection.disconnect()
    }
}
