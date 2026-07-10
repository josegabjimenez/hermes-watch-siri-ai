// swift-tools-version: 5.9
import PackageDescription

var dependencies: [Package.Dependency] = [
    .package(url: "https://github.com/apple/swift-crypto.git", from: "3.0.0")
]

var testDependencies: [Target.Dependency] = ["HermesCore"]

// Some standalone Swift 5.x toolchains do not bundle XCTest. In that case,
// compile the matching open-source XCTest package as an explicit dependency.
#if compiler(<6.0)
dependencies.append(
    .package(
        url: "https://github.com/swiftlang/swift-corelibs-xctest.git",
        revision: "aba63a74270b094db00c40182f8774afbe2a91e9" // swift-5.10-RELEASE
    )
)
testDependencies.append(
    .product(name: "XCTest", package: "swift-corelibs-xctest")
)
#endif

let package = Package(
    name: "HermesCore",
    platforms: [
        .iOS(.v17),
        .watchOS(.v10),
        .macOS(.v13)
    ],
    products: [
        .library(name: "HermesCore", targets: ["HermesCore"])
    ],
    dependencies: dependencies,
    targets: [
        .target(
            name: "HermesCore",
            dependencies: [
                .product(name: "Crypto", package: "swift-crypto")
            ]
        ),
        .testTarget(
            name: "HermesCoreTests",
            dependencies: testDependencies
        )
    ]
)
