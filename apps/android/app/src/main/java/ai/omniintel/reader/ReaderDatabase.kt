package ai.omniintel.reader

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
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

@Database(
    entities = [LibraryBookEntity::class, VideoImportEntity::class],
    version = 2,
    exportSchema = false
)
abstract class ReaderDatabase : RoomDatabase() {
    abstract fun libraryBooks(): LibraryBookDao
    abstract fun videoImports(): VideoImportDao

    companion object {
        private val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL(
                    """CREATE TABLE IF NOT EXISTS video_imports (
                        videoId TEXT NOT NULL PRIMARY KEY,
                        url TEXT NOT NULL,
                        createdAtEpochMs INTEGER NOT NULL,
                        status TEXT NOT NULL
                    )"""
                )
            }
        }

        @Volatile private var instance: ReaderDatabase? = null

        fun get(context: Context): ReaderDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    ReaderDatabase::class.java,
                    "omniintel_reader.db"
                ).addMigrations(MIGRATION_1_2)
                    .build().also { instance = it }
            }
    }
}
