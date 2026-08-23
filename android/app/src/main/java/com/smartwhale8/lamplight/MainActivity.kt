package com.smartwhale8.lamplight

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import com.smartwhale8.lamplight.ui.ControlScreen
import com.smartwhale8.lamplight.ui.DiscoveryScreen
import com.smartwhale8.lamplight.ui.LampViewModel
import com.smartwhale8.lamplight.ui.theme.LamplightTheme

/**
 * The only activity.
 *
 * Which screen shows is decided by whether a lamp is connected: with none, the discovery
 * screen; with one, the controls. Polling is tied to the activity lifecycle so the app
 * sends nothing while it is in the background.
 */
class MainActivity : ComponentActivity() {

    private var viewModelRef: LampViewModel? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            LamplightTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    LamplightApp(onViewModel = { viewModelRef = it })
                }
            }
        }
    }

    override fun onStop() {
        super.onStop()
        // The lamp has no push channel, so the app polls. Stop when out of sight; a
        // background poll would drain the battery and tell nobody anything.
        viewModelRef?.stopPolling()
    }

    override fun onStart() {
        super.onStart()
        viewModelRef?.startPolling()
    }
}

@Composable
private fun LamplightApp(onViewModel: (LampViewModel) -> Unit) {
    val vm: LampViewModel = viewModel()
    onViewModel(vm)
    val state by vm.state.collectAsState()

    Box(modifier = Modifier.fillMaxSize()) {
        if (state.device == null) {
            DiscoveryScreen(state = state, vm = vm)
        } else {
            ControlScreen(state = state, vm = vm)
        }
    }
}
