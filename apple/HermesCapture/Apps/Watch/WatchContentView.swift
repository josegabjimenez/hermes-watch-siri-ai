import SwiftUI
import HermesCore

struct WatchContentView: View {
    private let actions: [QuickActionKind] = [.expense, .reminder, .grocery, .general]

    var body: some View {
        NavigationStack {
            List(actions) { action in
                Button {
                    // Next implementation step: present system dictation/text input,
                    // enqueue payload locally, sign with HMAC V2, then submit to BFF.
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
