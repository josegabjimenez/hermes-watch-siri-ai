import SwiftUI
import HermesCore

struct IOSContentView: View {
    @State private var endpoint = "https://<TAILSCALE_DNS_NAME>:8650"

    var body: some View {
        NavigationStack {
            Form {
                Section("BFF endpoint") {
                    TextField("Base URL", text: $endpoint)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Text("Use a tailnet-only HTTPS endpoint during development. Store the route secret in Keychain, not in source or UserDefaults.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Section("Watch-first MVP") {
                    Label("Configure endpoint + secret on iPhone", systemImage: "iphone")
                    Label("Sync config to Watch", systemImage: "applewatch")
                    Label("Keep captures dry-run until Fable 5 gates pass", systemImage: "lock.shield")
                }
            }
            .navigationTitle("Hermes Capture")
        }
    }
}

#Preview {
    IOSContentView()
}
