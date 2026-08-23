package com.smartwhale8.limelight.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// A warm amber, chosen because the product is a lamp and the accent reads as limelight.
private val Amber = Color(0xFFC8811F)
private val AmberLight = Color(0xFFE0A44A)

private val LightColors = lightColorScheme(
    primary = Amber,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFFFDFB0),
    onPrimaryContainer = Color(0xFF2A1800),
    secondary = Color(0xFF6F5B40),
    background = Color(0xFFF6F7F9),
    surface = Color(0xFFFFFFFF),
    surfaceVariant = Color(0xFFEFF1F4),
    onSurfaceVariant = Color(0xFF697280),
    outline = Color(0xFFD8DCE2),
)

private val DarkColors = darkColorScheme(
    primary = AmberLight,
    onPrimary = Color(0xFF2A1800),
    primaryContainer = Color(0xFF5C4116),
    onPrimaryContainer = Color(0xFFFFDFB0),
    secondary = Color(0xFFD9C3A3),
    background = Color(0xFF0E1114),
    surface = Color(0xFF171B20),
    surfaceVariant = Color(0xFF262C34),
    onSurfaceVariant = Color(0xFF98A2B0),
    outline = Color(0xFF39414B),
)

private val AppTypography = Typography(
    titleLarge = TextStyle(fontSize = 20.sp, fontWeight = FontWeight.SemiBold),
    titleMedium = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.SemiBold),
    labelSmall = TextStyle(fontSize = 11.sp, fontWeight = FontWeight.Medium),
)

/**
 * Applies the app theme.
 *
 * On Android 12 and later the system's dynamic colour is used when available, so the app
 * matches the device's wallpaper palette. Otherwise the amber scheme above applies.
 */
@Composable
fun LimelightTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit,
) {
    val colors = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }
        darkTheme -> DarkColors
        else -> LightColors
    }
    MaterialTheme(colorScheme = colors, typography = AppTypography, content = content)
}
