import XCTest

#if DEBUG && targetEnvironment(simulator)
@MainActor
final class HermesCaptureUITests: XCTestCase {
    private var app: XCUIApplication!
    private var caseID = ""

    override func setUpWithError() throws {
        continueAfterFailure = false
        caseID = UUID().uuidString.lowercased()
        app = XCUIApplication()
    }

    override func tearDownWithError() throws {
        app?.terminate()
    }

    func testHomeOffersOnlyThreeApprovedCaptureActions() {
        launch()
        for action in ["grocery", "reminder", "expense"] {
            XCTAssertTrue(app.buttons["capture.\(action)"].waitForExistence(timeout: 5))
        }
        XCTAssertFalse(app.buttons["capture.general"].exists)
        XCTAssertFalse(app.buttons["Capturar"].exists)
        XCTAssertFalse(app.staticTexts["Capturar"].exists)
    }

    func testGroceryCaptureShowsCommittedResult() {
        launch()
        enterCapture("grocery", text: "leche")
        app.buttons["capture.send"].tap()
        assertStatusContains("Mercado actualizado")
        XCTAssertFalse(app.buttons["expense.confirm"].exists)
    }

    func testReminderShowsBogotaScheduleAndPendingAlerts() {
        launch()
        enterCapture("reminder", text: "recuérdame llamar mañana a las dos P.M.")
        app.buttons["capture.send"].tap()
        assertStatusContains("Bogotá")
        assertStatusContains("2:00")
        assertStatusContains("avisos pendientes")
    }

    func testExpenseRequiresExplicitConfirmationBeforeCommit() {
        launch()
        requestExpensePreview()
        XCTAssertTrue(app.buttons["expense.cancel"].exists)
        XCTAssertFalse(app.staticTexts["capture.status"].label.contains("Gasto registrado"))
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Efectivo")).firstMatch.exists)
        app.buttons["expense.confirm"].tap()
        assertStatusContains("Gasto registrado")
        XCTAssertFalse(app.buttons["expense.confirm"].exists)
        relaunchAndOpenExpense()
        assertNoRestoredConfirmation()
    }

    func testCancellationDoesNotRestorePreviewAfterRelaunch() {
        launch()
        requestExpensePreview()
        app.buttons["expense.cancel"].tap()
        assertStatusContains("cancelado")
        relaunchAndOpenExpense()
        assertNoRestoredConfirmation()
    }

    func testOfflineConfirmationCanBeCancelledWithoutRestoringPreview() {
        launch(scenario: "offline_confirmation")
        requestExpensePreview()
        app.buttons["expense.confirm"].tap()
        assertStatusContains("Sin conexión")
        XCTAssertTrue(app.buttons["expense.cancel"].waitForExistence(timeout: 5))
        app.buttons["expense.cancel"].tap()
        assertStatusContains("cancelado")
        relaunchAndOpenExpense()
        assertNoRestoredConfirmation()
    }

    func testExpiredPreviewIsTerminalAndNotRestored() {
        launch(scenario: "expired")
        requestExpensePreview()
        app.buttons["expense.confirm"].tap()
        assertStatusContains("vencida")
        XCTAssertFalse(app.buttons["expense.confirm"].exists)
        relaunchAndOpenExpense()
        assertNoRestoredConfirmation()
    }

    func testDoubleTapConfirmationLeavesOneTerminalResult() {
        launch()
        requestExpensePreview()
        app.buttons["expense.confirm"].doubleTap()
        assertStatusContains("Gasto registrado")
        XCTAssertFalse(app.buttons["expense.confirm"].exists)
        relaunchAndOpenExpense()
        assertNoRestoredConfirmation()
    }

    private func launch(scenario: String = "normal") {
        app.launchArguments = ["--hermes-synthetic-ui", "--hermes-ui-case=\(caseID)",
                               "--hermes-ui-scenario=\(scenario)"]
        app.launch()
    }

    private func enterCapture(_ action: String, text: String) {
        let entry = app.buttons["capture.\(action)"]
        XCTAssertTrue(entry.waitForExistence(timeout: 5))
        entry.tap()
        let field = app.textFields["capture.text"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap()
        field.typeText(text)
        XCTAssertTrue(app.buttons["capture.send"].isEnabled)
    }

    private func requestExpensePreview() {
        enterCapture("expense", text: "45 mil en Uber")
        app.buttons["capture.send"].tap()
        XCTAssertTrue(app.buttons["expense.confirm"].waitForExistence(timeout: 5))
    }

    private func relaunchAndOpenExpense() {
        app.terminate()
        // The same case argument deliberately retains only this test's outbox.
        app.launch()
        let entry = app.buttons["capture.expense"]
        XCTAssertTrue(entry.waitForExistence(timeout: 5))
        entry.tap()
        XCTAssertTrue(app.textFields["capture.text"].waitForExistence(timeout: 5))
    }

    private func assertNoRestoredConfirmation(file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertFalse(app.buttons["expense.confirm"].waitForExistence(timeout: 1), file: file, line: line)
        XCTAssertFalse(app.buttons["expense.cancel"].exists, file: file, line: line)
    }

    private func assertStatusContains(_ text: String, file: StaticString = #filePath, line: UInt = #line) {
        let status = app.staticTexts["capture.status"]
        let predicate = NSPredicate(format: "exists == true AND label CONTAINS %@", text)
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: status)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 5), .completed, file: file, line: line)
    }
}
#endif
