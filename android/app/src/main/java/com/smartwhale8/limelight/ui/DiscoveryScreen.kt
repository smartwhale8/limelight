package com.smartwhale8.limelight.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Lightbulb
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.smartwhale8.limelight.miio.DiscoveredDevice
import com.smartwhale8.limelight.miio.Subnet

/**
 * Finds lamps on the local network and lets the user connect to one.
 *
 * Discovery is the unencrypted miIO handshake, so no credential is needed to list
 * devices. A device that discloses its token connects in one tap. One that withholds it
 * prompts for a token, which is the only case where the user has to supply anything.
 */
@Composable
fun DiscoveryScreen(state: UiState, vm: LampViewModel) {
    val snackbar = remember { SnackbarHostState() }

    var pickedSubnet by remember { mutableStateOf<String?>(null) }
    var useOther by remember { mutableStateOf(false) }
    var otherInput by remember { mutableStateOf("") }

    // The picked network can disappear when a VPN stops, and Wi-Fi is first otherwise.
    val picked = state.targets.firstOrNull { it.subnet == pickedSubnet } ?: state.targets.firstOrNull()
    val otherSubnet = Subnet.parse(otherInput)

    LaunchedEffect(state.message) {
        state.message?.let {
            snackbar.showSnackbar(it)
            vm.dismissMessage()
        }
    }

    // Scan once on first open, so the screen is not just an empty button.
    LaunchedEffect(Unit) {
        if (state.found.isEmpty() && !state.scanning) vm.scan()
    }

    Scaffold(snackbarHost = { SnackbarHost(snackbar) }) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 20.dp),
        ) {
            Spacer(Modifier.height(24.dp))
            Text("Find a lamp", style = MaterialTheme.typography.titleLarge)
            Text(
                text = if (state.targets.isEmpty()) "Not connected to Wi-Fi"
                else "Choose the network to scan",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            Spacer(Modifier.height(12.dp))

            Column(modifier = Modifier.selectableGroup()) {
                state.targets.forEach { target ->
                    NetworkOption(
                        selected = !useOther && target == picked,
                        title = target.kind.label,
                        detail = target.cidr,
                        onClick = {
                            useOther = false
                            pickedSubnet = target.subnet
                        },
                    )
                }
                NetworkOption(
                    selected = useOther,
                    title = "Other subnet",
                    onClick = { useOther = true },
                )
            }

            if (useOther) {
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = otherInput,
                    onValueChange = { otherInput = it },
                    label = { Text("Subnet to scan") },
                    singleLine = true,
                    enabled = !state.scanning,
                    isError = otherInput.isNotBlank() && otherSubnet == null,
                    supportingText = { Text("Scans the /24, for example 192.168.1.0") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            Spacer(Modifier.height(12.dp))

            if (state.scanning) {
                LinearProgressIndicator(
                    progress = { state.scanProgress },
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    "Scanning…",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                Button(
                    onClick = { vm.scan(if (useOther) otherSubnet else picked?.subnet) },
                    enabled = !useOther || otherSubnet != null,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(
                        if (state.found.isEmpty()) Icons.Filled.Search else Icons.Filled.Refresh,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(if (state.found.isEmpty()) "Scan for lamps" else "Scan again")
                }
            }

            Spacer(Modifier.height(20.dp))

            LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(state.found, key = { it.address }) { device ->
                    DeviceCard(device = device, onClick = { vm.connect(device) })
                }
            }

            if (state.found.isEmpty() && !state.scanning) {
                Text(
                    "Nothing found yet. Make sure the lamp has power and that this phone " +
                        "is on the same Wi-Fi network as the lamp.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }

    state.awaitingTokenFor?.let { device ->
        TokenDialog(
            device = device,
            onDismiss = { vm.cancelTokenEntry() },
            onConfirm = { token -> vm.connectWithToken(device, token) },
        )
    }
}

@Composable
private fun NetworkOption(
    selected: Boolean,
    title: String,
    detail: String? = null,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .selectable(selected = selected, role = Role.RadioButton, onClick = onClick)
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected = selected, onClick = null)
        Spacer(Modifier.width(12.dp))
        Text(title, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
        if (detail != null) {
            Text(
                detail,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun DeviceCard(device: DiscoveredDevice, onClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                Icons.Filled.Lightbulb,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
            )
            Spacer(Modifier.width(14.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(device.address, style = MaterialTheme.typography.titleMedium)
                Text(
                    text = "Device ${device.deviceId}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = if (device.tokenDisclosed) "Ready to connect"
                    else "Needs a token",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (device.tokenDisclosed) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            TextButton(onClick = onClick) { Text("Connect") }
        }
    }
}

/**
 * Asks for a token, for a device whose firmware withholds it.
 *
 * This happens when the device has been bound to a vendor cloud account, which
 * regenerates the token and stops the handshake disclosing it.
 */
@Composable
private fun TokenDialog(
    device: DiscoveredDevice,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
) {
    var token by remember { mutableStateOf("") }
    val valid = token.trim().length == 32

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Token needed") },
        text = {
            Column {
                Text(
                    "The device at ${device.address} did not disclose its token, which " +
                        "means it has been paired with a vendor account. Enter its " +
                        "32-character token to continue.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(Modifier.height(16.dp))
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it.filter { c -> !c.isWhitespace() } },
                    label = { Text("Token") },
                    singleLine = true,
                    isError = token.isNotEmpty() && !valid,
                    supportingText = { Text("${token.trim().length} of 32 characters") },
                    keyboardOptions = KeyboardOptions(
                        capitalization = KeyboardCapitalization.None,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onConfirm(token) }, enabled = valid) { Text("Connect") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

