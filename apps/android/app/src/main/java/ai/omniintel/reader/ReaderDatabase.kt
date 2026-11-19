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

@Database(entities = [LibraryBookEntity::class], version = 1, exportSchema = false)
abstract class ReaderDatabase : RoomDatabase() {
    abstract fun libraryBooks(): LibraryBookDao

    companion object {
        @Volatile private var instance: ReaderDatabase? = null

        fun get(context: Context): ReaderDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    ReaderDatabase::class.java,
                    "omniintel_reader.db"
                ).build().also { instance = it }
            }
    }
}
