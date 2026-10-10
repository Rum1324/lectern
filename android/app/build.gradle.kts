import java.util.Properties

plugins {
    id("com.android.application")
}

// Release signing key lives outside the repo (see CLAUDE.md). Without it, release builds are unsigned.
val signing = Properties().apply {
    val f = File(System.getProperty("user.home"), ".config/lectern/android-signing.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "com.lectern.hid"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.lectern.hid"
        minSdk = 28 // BluetoothHidDevice
        targetSdk = 36
        versionCode = 5
        versionName = "0.5.0"
    }
    signingConfigs {
        if (signing.isNotEmpty()) create("release") {
            storeFile = File(signing.getProperty("storeFile"))
            storePassword = signing.getProperty("storePassword")
            keyAlias = signing.getProperty("keyAlias")
            keyPassword = signing.getProperty("keyPassword")
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release")
        }
    }
}

// The UI is the web app itself: web/index.html is copied into the APK's assets on every build,
// so the phone page and the Android app never drift apart.
abstract class CopyWebApp : DefaultTask() {
    @get:InputFile abstract val page: RegularFileProperty
    @get:OutputDirectory abstract val outputDir: DirectoryProperty

    @TaskAction
    fun copy() {
        val out = outputDir.get().asFile
        out.deleteRecursively()
        out.mkdirs()
        page.get().asFile.copyTo(File(out, "index.html"))
    }
}

val copyWebApp = tasks.register<CopyWebApp>("copyWebApp") {
    page.set(rootProject.layout.projectDirectory.file("../web/index.html"))
}

androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(copyWebApp, CopyWebApp::outputDir)
    }
}
