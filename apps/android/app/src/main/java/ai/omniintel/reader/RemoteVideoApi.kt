package ai.omniintel.reader

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

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
