package ai.omniintel.reader

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Entity(tableName = "library_books")
data class LibraryBookEntity(
    @PrimaryKey val versionId: String,
    val title: String,
    val documentUri: String,
    val sourceCount: Int,
    val chapterCount: Int,
    val importedAtEpochMs: Long,
    val lastOpenedAtEpochMs: Long
)

data class LibrarySearchResult(
    val versionId: String,
    val bookTitle: String,
    val chapterIndex: Int,
    val chapterTitle: String,
    val blockId: String,
    val blockType: String,
    val blockText: String,
    val note: String?
)

@Dao
interface LibraryBookDao {
    @Query("SELECT * FROM library_books ORDER BY lastOpenedAtEpochMs DESC, importedAtEpochMs DESC")
    suspend fun getAll(): List<LibraryBookEntity>

    @Query("SELECT * FROM library_books WHERE versionId = :versionId LIMIT 1")
    suspend fun find(versionId: String): LibraryBookEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(book: LibraryBookEntity)

    @Query("DELETE FROM library_books WHERE versionId = :versionId")
    suspend fun delete(versionId: String)

    @Query("""
        SELECT b.versionId AS versionId, l.title AS bookTitle,
               c.chapterIndex AS chapterIndex, c.title AS chapterTitle,
               b.blockId AS blockId, b.blockType AS blockType,
               b.text AS blockText, a.note AS note
        FROM textbook_blocks AS b
        INNER JOIN textbook_chapters AS c
          ON c.versionId = b.versionId AND c.chapterIndex = b.chapterIndex
        INNER JOIN library_books AS l ON l.versionId = b.versionId
        LEFT JOIN reader_annotations AS a
          ON a.versionId = b.versionId AND a.blockId = b.blockId
        WHERE l.title LIKE '%' || :query || '%'
           OR c.title LIKE '%' || :query || '%'
           OR b.text LIKE '%' || :query || '%'
           OR COALESCE(a.note, '') LIKE '%' || :query || '%'
           OR EXISTS (
               SELECT 1 FROM textbook_evidence AS e
               WHERE e.versionId = b.versionId AND e.blockId = b.blockId
                 AND (e.excerpt LIKE '%' || :query || '%'
                   OR e.sourceTitle LIKE '%' || :query || '%')
           )
        ORDER BY l.lastOpenedAtEpochMs DESC, c.chapterIndex, b.blockIndex
        LIMIT 250
    """)
    suspend fun searchLibrary(query: String): List<LibrarySearchResult>
}

@Entity(tableName = "video_imports")
data class VideoImportEntity(
    @PrimaryKey val videoId: String,
    val url: String,
    val createdAtEpochMs: Long,
    val status: String
)

@Dao
interface VideoImportDao {
    @Query("SELECT * FROM video_imports ORDER BY createdAtEpochMs DESC")
    suspend fun getAll(): List<VideoImportEntity>

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertIfAbsent(item: VideoImportEntity): Long

    @Query("DELETE FROM video_imports WHERE videoId = :videoId")
    suspend fun delete(videoId: String)
}

@Entity(tableName = "textbook_sources", primaryKeys = ["versionId", "sourceId"])
data class TextbookSourceEntity(val versionId: String, val sourceId: String, val title: String)

@Entity(tableName = "textbook_chapters", primaryKeys = ["versionId", "chapterIndex"])
data class TextbookChapterEntity(val versionId: String, val chapterIndex: Int, val title: String)

@Entity(
    tableName = "textbook_blocks",
    primaryKeys = ["versionId", "blockId"],
    foreignKeys = [ForeignKey(
        entity = TextbookChapterEntity::class,
        parentColumns = ["versionId", "chapterIndex"],
        childColumns = ["versionId", "chapterIndex"],
        onDelete = ForeignKey.CASCADE
    )],
    indices = [Index(value = ["versionId", "chapterIndex"]), Index(value = ["versionId", "blockType"])]
)
data class TextbookBlockEntity(
    val versionId: String,
    val blockId: String,
    val chapterIndex: Int,
    val blockIndex: Int,
    val blockType: String,
    val text: String,
    val provenance: String
)

@Entity(
    tableName = "textbook_evidence",
    primaryKeys = ["versionId", "blockId", "evidenceIndex"],
    foreignKeys = [ForeignKey(
        entity = TextbookBlockEntity::class,
        parentColumns = ["versionId", "blockId"],
        childColumns = ["versionId", "blockId"],
        onDelete = ForeignKey.CASCADE
    )],
    indices = [Index(value = ["versionId", "blockId"]), Index(value = ["sourceId"])]
)
data class TextbookEvidenceEntity(
    val versionId: String,
    val blockId: String,
    val evidenceIndex: Int,
    val sourceId: String,
    val sourceTitle: String,
    val locator: String,
    val startMs: Long?,
    val excerpt: String
)

@Entity(tableName = "reader_annotations", primaryKeys = ["versionId", "blockId"])
data class ReaderAnnotationEntity(
    val versionId: String,
    val blockId: String,
    val note: String?,
    val bookmarked: Boolean,
    val updatedAtEpochMs: Long
)

@Entity(tableName = "reader_progress")
data class ReaderProgressEntity(
    @PrimaryKey val versionId: String,
    val chapterIndex: Int,
    val lastBlockId: String?,
    val updatedAtEpochMs: Long
)

@Entity(tableName = "reader_migrations")
data class ReaderMigrationEntity(@PrimaryKey val migrationKey: String, val completedAtEpochMs: Long)

@Dao
interface ReaderContentDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun insertSources(items: List<TextbookSourceEntity>)
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun insertChapters(items: List<TextbookChapterEntity>)
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun insertBlocks(items: List<TextbookBlockEntity>)
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun insertEvidence(items: List<TextbookEvidenceEntity>)

    @Query("DELETE FROM textbook_chapters WHERE versionId = :versionId")
    suspend fun deleteChapters(versionId: String)

    @Query("DELETE FROM textbook_sources WHERE versionId = :versionId")
    suspend fun deleteSources(versionId: String)

    @Query("SELECT * FROM textbook_sources WHERE versionId = :versionId ORDER BY sourceId")
    suspend fun sources(versionId: String): List<TextbookSourceEntity>

    @Query("SELECT * FROM textbook_chapters WHERE versionId = :versionId ORDER BY chapterIndex")
    suspend fun chapters(versionId: String): List<TextbookChapterEntity>

    @Query("SELECT * FROM textbook_blocks WHERE versionId = :versionId ORDER BY chapterIndex, blockIndex")
    suspend fun blocks(versionId: String): List<TextbookBlockEntity>

    @Query("SELECT * FROM textbook_evidence WHERE versionId = :versionId ORDER BY blockId, evidenceIndex")
    suspend fun evidence(versionId: String): List<TextbookEvidenceEntity>
}

@Dao
interface ReaderAnnotationDao {
    @Query("SELECT * FROM reader_annotations WHERE versionId = :versionId")
    suspend fun forVersion(versionId: String): List<ReaderAnnotationEntity>

    @Query("SELECT * FROM reader_annotations ORDER BY versionId, blockId")
    suspend fun getAll(): List<ReaderAnnotationEntity>

    @Query("SELECT * FROM reader_annotations WHERE versionId = :versionId AND blockId = :blockId LIMIT 1")
    suspend fun find(versionId: String, blockId: String): ReaderAnnotationEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun upsert(item: ReaderAnnotationEntity)
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun upsertAll(items: List<ReaderAnnotationEntity>)

    @Query("DELETE FROM reader_annotations WHERE versionId = :versionId")
    suspend fun deleteForVersion(versionId: String)
}

@Dao
interface ReaderProgressDao {
    @Query("SELECT * FROM reader_progress WHERE versionId = :versionId LIMIT 1")
    suspend fun find(versionId: String): ReaderProgressEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun upsert(item: ReaderProgressEntity)

    @Query("DELETE FROM reader_progress WHERE versionId = :versionId")
    suspend fun delete(versionId: String)
}

@Dao
interface ReaderMigrationDao {
    @Query("SELECT * FROM reader_migrations WHERE migrationKey = :key LIMIT 1")
    suspend fun find(key: String): ReaderMigrationEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun insert(item: ReaderMigrationEntity)
}

@Database(
    entities = [
        LibraryBookEntity::class, VideoImportEntity::class, TextbookSourceEntity::class,
        TextbookChapterEntity::class, TextbookBlockEntity::class, TextbookEvidenceEntity::class,
        ReaderAnnotationEntity::class, ReaderProgressEntity::class, ReaderMigrationEntity::class
    ],
    version = 3,
    exportSchema = false
)
abstract class ReaderDatabase : RoomDatabase() {
    abstract fun libraryBooks(): LibraryBookDao
    abstract fun videoImports(): VideoImportDao
    abstract fun readerContent(): ReaderContentDao
    abstract fun annotations(): ReaderAnnotationDao
    abstract fun progress(): ReaderProgressDao
    abstract fun migrations(): ReaderMigrationDao

    companion object {
        private val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL("""CREATE TABLE IF NOT EXISTS video_imports (
                    videoId TEXT NOT NULL PRIMARY KEY, url TEXT NOT NULL,
                    createdAtEpochMs INTEGER NOT NULL, status TEXT NOT NULL)""")
            }
        }

        private val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL("""CREATE TABLE IF NOT EXISTS textbook_sources (
                    versionId TEXT NOT NULL, sourceId TEXT NOT NULL, title TEXT NOT NULL,
                    PRIMARY KEY(versionId, sourceId))""")
                database.execSQL("""CREATE TABLE IF NOT EXISTS textbook_chapters (
                    versionId TEXT NOT NULL, chapterIndex INTEGER NOT NULL, title TEXT NOT NULL,
                    PRIMARY KEY(versionId, chapterIndex))""")
                database.execSQL("""CREATE TABLE IF NOT EXISTS textbook_blocks (
                    versionId TEXT NOT NULL, blockId TEXT NOT NULL, chapterIndex INTEGER NOT NULL,
                    blockIndex INTEGER NOT NULL, blockType TEXT NOT NULL, text TEXT NOT NULL,
                    provenance TEXT NOT NULL, PRIMARY KEY(versionId, blockId),
                    FOREIGN KEY(versionId, chapterIndex) REFERENCES textbook_chapters(versionId, chapterIndex)
                    ON UPDATE NO ACTION ON DELETE CASCADE)""")
                database.execSQL("CREATE INDEX IF NOT EXISTS index_textbook_blocks_versionId_chapterIndex ON textbook_blocks(versionId, chapterIndex)")
                database.execSQL("CREATE INDEX IF NOT EXISTS index_textbook_blocks_versionId_blockType ON textbook_blocks(versionId, blockType)")
                database.execSQL("""CREATE TABLE IF NOT EXISTS textbook_evidence (
                    versionId TEXT NOT NULL, blockId TEXT NOT NULL, evidenceIndex INTEGER NOT NULL,
                    sourceId TEXT NOT NULL, sourceTitle TEXT NOT NULL, locator TEXT NOT NULL,
                    startMs INTEGER, excerpt TEXT NOT NULL, PRIMARY KEY(versionId, blockId, evidenceIndex),
                    FOREIGN KEY(versionId, blockId) REFERENCES textbook_blocks(versionId, blockId)
                    ON UPDATE NO ACTION ON DELETE CASCADE)""")
                database.execSQL("CREATE INDEX IF NOT EXISTS index_textbook_evidence_versionId_blockId ON textbook_evidence(versionId, blockId)")
                database.execSQL("CREATE INDEX IF NOT EXISTS index_textbook_evidence_sourceId ON textbook_evidence(sourceId)")
                database.execSQL("""CREATE TABLE IF NOT EXISTS reader_annotations (
                    versionId TEXT NOT NULL, blockId TEXT NOT NULL, note TEXT, bookmarked INTEGER NOT NULL,
                    updatedAtEpochMs INTEGER NOT NULL, PRIMARY KEY(versionId, blockId))""")
                database.execSQL("""CREATE TABLE IF NOT EXISTS reader_progress (
                    versionId TEXT NOT NULL PRIMARY KEY, chapterIndex INTEGER NOT NULL,
                    lastBlockId TEXT, updatedAtEpochMs INTEGER NOT NULL)""")
                database.execSQL("""CREATE TABLE IF NOT EXISTS reader_migrations (
                    migrationKey TEXT NOT NULL PRIMARY KEY, completedAtEpochMs INTEGER NOT NULL)""")
            }
        }

        @Volatile private var instance: ReaderDatabase? = null

        fun get(context: Context): ReaderDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    ReaderDatabase::class.java,
                    "omniintel_reader.db"
                ).addMigrations(MIGRATION_1_2, MIGRATION_2_3)
                    .build().also { instance = it }
            }
    }
}
