import SwiftUI
import HermesCore

@main
struct HermesCaptureWatchApp: App {
    @StateObject private var bootstrapReceiver = WatchBootstrapReceiver()

    var body: some Scene {
        WindowGroup {
            WatchContentView()
                .environmentObject(bootstrapReceiver)
        }
    }
}
