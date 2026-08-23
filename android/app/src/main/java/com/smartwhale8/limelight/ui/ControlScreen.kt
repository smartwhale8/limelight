package com.smartwhale8.limelight.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.Power
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.smartwhale8.limelight.device.Capability

/** Longest sleep timer the slider offers. The device itself accepts more. */
private const val TIMER_MAX_MINUTES = 120

/** Slider granularity, so a drag lands on a round number. */
private const val TIMER_STEP_MINUTES = 5

/**
 * Controls for a connected lamp.
 *
 * Every control is rendered from the driver's capability set rather than assumed, so a
 * different model shows a different set of controls with no change here.
 *
 * Sliders commit on release rather than continuously. The lamp is a single-threaded
 * microcontroller on UDP, and a datagram per pixel of travel would simply be dropped.
 */
@Composable
fun ControlScreen(state: UiState, vm: LampViewModel) {
    val snackbar = remember { SnackbarHostState() }
    val device = state.device ?: return
    val lamp = state.lamp

    LaunchedEffect(state.message) {
        state.message?.let {
            snackbar.showSnackbar(it)
            vm.dismissMessage()
        }
    }

    Scaffold(snackbarHost = { SnackbarHost(snackbar) }) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Spacer(Modifier.height(10.dp))

            Header(
                label = device.label,
                address = device.address,
                reachable = state.reachable,
                onDisconnect = { vm.disconnect() },
            )

            if (device.capabilities.contains(Capability.POWER)) {
                PowerCard(
                    on = lamp?.on == true,
                    enabled = lamp != null,
                    onToggle = { vm.setPower(it) },
                )
            }

            if (device.capabilities.contains(Capability.BRIGHTNESS) && lamp?.brightness != null) {
                SliderCard(
                    title = "Brightness",
                    subtitle = "Main light",
                    value = lamp.brightness,
                    onCommit = { vm.setBrightness(it) },
                )
            }

            if (device.capabilities.contains(Capability.SLEEP_TIMER)) {
                SleepTimerCard(
                    minutesRemaining = lamp?.sleepTimerMinutes ?: 0,
                    onSet = { vm.setSleepTimer(it) },
                )
            }

            ModesCard(state = state, vm = vm)

            if (device.capabilities.contains(Capability.SCENES) && device.scenes.isNotEmpty()) {
                ScenesCard(
                    scenes = device.scenes,
                    current = lamp?.scene,
                    onSelect = { vm.setScene(it) },
                )
            }

            Spacer(Modifier.height(28.dp))
        }
    }
}

// ---------------------------------------------------------------------------- header

@Composable
private fun Header(
    label: String,
    address: String,
    reachable: Boolean,
    onDisconnect: () -> Unit,
) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.titleLarge)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(7.dp)
                        .clip(CircleShape)
                        .background(
                            if (reachable) MaterialTheme.colorScheme.primary
                            else MaterialTheme.colorScheme.error
                        )
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    text = if (reachable) address else "$address · not responding",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        TextButton(onClick = onDisconnect) {
            Icon(Icons.Filled.Link, contentDescription = null, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text("Change")
        }
    }
}

// ----------------------------------------------------------------------------- cards

@Composable
private fun SectionCard(
    title: String? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            if (title != null) {
                Text(
                    title.uppercase(),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(12.dp))
            }
            content()
        }
    }
}

@Composable
private fun PowerCard(on: Boolean, enabled: Boolean, onToggle: (Boolean) -> Unit) {
    Button(
        onClick = { onToggle(!on) },
        enabled = enabled,
        modifier = Modifier
            .fillMaxWidth()
            .height(72.dp),
        shape = RoundedCornerShape(16.dp),
        colors = if (on) {
            ButtonDefaults.buttonColors()
        } else {
            ButtonDefaults.buttonColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
                contentColor = MaterialTheme.colorScheme.onSurface,
            )
        },
    ) {
        Icon(Icons.Filled.Power, contentDescription = null, modifier = Modifier.size(22.dp))
        Spacer(Modifier.width(10.dp))
        Text(
            text = if (on) "On" else "Off",
            fontSize = 18.sp,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
private fun SliderCard(
    title: String,
    subtitle: String,
    value: Int,
    onCommit: (Int) -> Unit,
) {
    // Local position so the thumb tracks the finger; the command is sent on release.
    var dragging by remember { mutableStateOf(false) }
    var position by remember { mutableFloatStateOf(value.toFloat()) }
    if (!dragging && position.toInt() != value) position = value.toFloat()

    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(modifier = Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleMedium)
                Text(
                    subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                "${position.toInt()}%",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Slider(
            value = position,
            onValueChange = {
                dragging = true
                position = it
            },
            onValueChangeFinished = {
                dragging = false
                onCommit(position.toInt())
            },
            valueRange = 1f..100f,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

/** Format a duration the way the interface shows it. */
private fun timerLabel(minutes: Int): String = when {
    minutes <= 0 -> "Off"
    minutes < 60 -> "$minutes min"
    minutes % 60 == 0 -> "${minutes / 60} h"
    else -> "${minutes / 60} h ${minutes % 60} min"
}

/**
 * The sleep timer, as a slider with a cancel action.
 *
 * An earlier version used four equal-width buttons, and "Clear" is longer than "15m", so
 * the label clipped inside its quarter of the row. A slider also covers every duration
 * rather than three presets, and cancelling is just dragging to zero.
 */
@Composable
private fun SleepTimerCard(minutesRemaining: Int, onSet: (Int) -> Unit) {
    var dragging by remember { mutableStateOf(false) }
    var position by remember { mutableFloatStateOf(minutesRemaining.toFloat()) }
    if (!dragging && position.toInt() != minutesRemaining) {
        position = minutesRemaining.coerceAtMost(TIMER_MAX_MINUTES).toFloat()
    }

    SectionCard(title = "Sleep timer") {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(modifier = Modifier.weight(1f)) {
                Text("Switch off after", style = MaterialTheme.typography.bodyLarge)
                Text(
                    "Counts down on the lamp, so it works with the phone away",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                timerLabel(position.toInt()),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Spacer(Modifier.height(4.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Slider(
                value = position,
                onValueChange = {
                    dragging = true
                    position = it
                },
                onValueChangeFinished = {
                    dragging = false
                    onSet(position.toInt())
                },
                valueRange = 0f..TIMER_MAX_MINUTES.toFloat(),
                steps = (TIMER_MAX_MINUTES / TIMER_STEP_MINUTES) - 1,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(4.dp))
            IconButton(
                onClick = {
                    position = 0f
                    onSet(0)
                },
                enabled = minutesRemaining > 0,
            ) {
                Icon(
                    Icons.Filled.Close,
                    contentDescription = "Cancel the sleep timer",
                    modifier = Modifier.size(20.dp),
                )
            }
        }
    }
}

@Composable
private fun ModesCard(state: UiState, vm: LampViewModel) {
    val device = state.device ?: return
    val lamp = state.lamp
    val caps = device.capabilities

    val hasAnyMode = caps.contains(Capability.EYECARE) || caps.contains(Capability.AMBIENT) ||
        caps.contains(Capability.NIGHT_LIGHT) || caps.contains(Capability.REMINDER)
    if (!hasAnyMode) return

    SectionCard(title = "Modes") {
        if (caps.contains(Capability.EYECARE)) {
            ToggleRow(
                title = "Eyecare",
                subtitle = "Sets its own brightness; the slider turns it off",
                checked = lamp?.eyecare == true,
                onChange = { vm.setEyecare(it) },
            )
        }
        if (caps.contains(Capability.AMBIENT)) {
            ToggleRow(
                title = "Ambient light",
                subtitle = "The second light in the base",
                checked = lamp?.ambientOn == true,
                onChange = { vm.setAmbient(it) },
            )
        }
        if (caps.contains(Capability.AMBIENT_BRIGHTNESS) && lamp?.ambientBrightness != null) {
            AmbientSlider(value = lamp.ambientBrightness) { vm.setAmbientBrightness(it) }
        }
        if (caps.contains(Capability.NIGHT_LIGHT)) {
            ToggleRow(
                title = "Smart night light",
                subtitle = "Dim output when the room is dark",
                checked = lamp?.nightLight == true,
                onChange = { vm.setNightLight(it) },
            )
        }
        if (caps.contains(Capability.REMINDER)) {
            ToggleRow(
                title = "Fatigue reminder",
                subtitle = "Prompts a break after prolonged use",
                checked = lamp?.reminder == true,
                onChange = { vm.setReminder(it) },
            )
        }
    }
}

@Composable
private fun AmbientSlider(value: Int, onCommit: (Int) -> Unit) {
    var dragging by remember { mutableStateOf(false) }
    var position by remember { mutableFloatStateOf(value.toFloat()) }
    if (!dragging && position.toInt() != value) position = value.toFloat()

    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
        Text(
            "Ambient brightness",
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.weight(1f),
        )
        Text("${position.toInt()}%", style = MaterialTheme.typography.bodyMedium)
    }
    Slider(
        value = position,
        onValueChange = {
            dragging = true
            position = it
        },
        onValueChangeFinished = {
            dragging = false
            onCommit(position.toInt())
        },
        valueRange = 1f..100f,
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun ToggleRow(
    title: String,
    subtitle: String,
    checked: Boolean,
    onChange: (Boolean) -> Unit,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(
                subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

@Composable
private fun ScenesCard(scenes: Map<Int, String>, current: Int?, onSelect: (Int) -> Unit) {
    SectionCard(title = "Scenes") {
        val entries = scenes.entries.sortedBy { it.key }
        entries.chunked(2).forEach { pair ->
            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 8.dp),
            ) {
                pair.forEach { (number, name) ->
                    val selected = current == number
                    if (selected) {
                        Button(onClick = { onSelect(number) }, modifier = Modifier.weight(1f)) {
                            Text(name)
                        }
                    } else {
                        OutlinedButton(
                            onClick = { onSelect(number) },
                            modifier = Modifier.weight(1f),
                        ) { Text(name) }
                    }
                }
                if (pair.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}

