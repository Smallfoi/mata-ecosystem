import java.util.Properties
import java.io.FileInputStream

plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Подпись релиза постоянным ключом (release-keystore). key.properties и сам .jks —
// вне git (.gitignore), ключ лежит в ~/.mata-keys. Если файла нет (чужой чекаут без
// ключа) — падаем на debug-подпись, чтобы `flutter run` и CI-проверки (analyze/test)
// работали без секретов. Обновление «поверх» на телефоне возможно только при ТОЙ ЖЕ
// подписи — поэтому ключ постоянный и его нельзя терять.
val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}
val hasReleaseKeystore = keystorePropertiesFile.exists()

android {
    namespace = "ru.mata.kvartal"
    // 36, а не flutter.compileSdkVersion (35): androidx.health.connect собирается
    // только против Android 16. Компиляция против нового SDK — не то же самое, что
    // targetSdk: поведение приложения на телефонах от этого не меняется.
    compileSdk = 36
    ndkVersion = "27.0.12077973"

    compileOptions {
        // flutter_local_notifications (zonedSchedule) требует desugaring java.time.
        isCoreLibraryDesugaringEnabled = true
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_11.toString()
    }

    defaultConfig {
        applicationId = "ru.mata.kvartal"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        // mobile_scanner (скан QR клуба) требует minSdk 23, health (Health Connect) — 26.
        // Берём больший: Health Connect и так живёт с Android 9, так что мы никого
        // не теряем сверх того, кого уже потеряли.
        minSdk = maxOf(flutter.minSdkVersion, 26)
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (hasReleaseKeystore) {
            create("release") {
                keyAlias = keystoreProperties["keyAlias"] as String
                keyPassword = keystoreProperties["keyPassword"] as String
                storeFile = file(keystoreProperties["storeFile"] as String)
                storePassword = keystoreProperties["storePassword"] as String
            }
        }
    }

    buildTypes {
        release {
            signingConfig = if (hasReleaseKeystore) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }
}

flutter {
    source = "../.."
}

dependencies {
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.4")
}
