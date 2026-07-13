import SwiftUI
import HermesCore

struct WatchContentView: View {
    private let actions: [QuickActionKind] = [.expense, .reminder, .grocery, .general]

    var body: some View {
        NavigationStack {
            List(actions) { action in
                NavigationLink {
                    WatchCaptureView(action: action)
                } label: {
                    Label(action.title, systemImage: action.symbolName)
                }
            }
            .navigationTitle("Hermes")
        }
    }
}

#Preview {
    WatchContentView()
}
