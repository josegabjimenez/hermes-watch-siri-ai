import SwiftUI
import HermesCore

struct WatchContentView: View {
    @EnvironmentObject private var bootstrapReceiver: WatchBootstrapReceiver

    private let actions: [QuickActionKind] = [.expense, .reminder, .grocery, .general]

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(actions) { action in
                        NavigationLink {
                            WatchCaptureView(action: action)
                        } label: {
                            Label(action.title, systemImage: action.symbolName)
                        }
                    }
                }

                Section {
                    Label(
                        bootstrapReceiver.statusMessage,
                        systemImage: bootstrapReceiver.isConfigured ? "checkmark.shield" : "iphone.gen3"
                    )
                    .font(.footnote)
                    .foregroundStyle(bootstrapReceiver.isConfigured ? .green : .secondary)
                }
            }
            .navigationTitle("Hermes")
        }
    }
}

#Preview {
    WatchContentView()
        .environmentObject(WatchBootstrapReceiver())
}
