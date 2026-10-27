#include <llvm/ADT/STLExtras.h>
#include <llvm/ExecutionEngine/ExecutionEngine.h>
#include <llvm/ExecutionEngine/GenericValue.h>
#include <llvm/IR/Constants.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/Support/ManagedStatic.h>
#include <llvm/Support/TargetSelect.h>

#include "foundations/Database.hpp"
#include "queryCompiler/queryCompiler.hpp"
#include <readline/readline.h>
#include <readline/history.h>

#include <chrono>
#include <cstdlib>

void prompt()
{
    std::unique_ptr<Database> currentdb = std::make_unique<Database>();
    // TARDIS_TIMING=1 prints the wall-clock time of every statement to stderr
    const bool printTiming = std::getenv("TARDIS_TIMING") != nullptr;
    while (true) {
        char *input = readline(">>> ");
        if (input == nullptr) { // end of input: Ctrl-D or end of a piped file
            break;
        }
        std::string line(input);
        free(input); // readline allocates the line, we must free it

        if (line == "quit") {
            break;
        }
        if (line.empty()) {
            continue;
        }
        add_history(line.c_str());

        const auto start = std::chrono::steady_clock::now();
        try {
            QueryCompiler::compileAndExecute(line, *currentdb);
        } catch (const std::exception & e) {
            fprintf(stderr, "Exception: %s\n", e.what());
        }
        if (printTiming) {
            const auto us = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - start).count();
            fprintf(stderr, "[time] %lld us  %s\n", static_cast<long long>(us), line.c_str());
        }
    }
}

int main(int argc, char * argv[])
{
    // necessary for the LLVM JIT compiler
    llvm::InitializeNativeTarget();
    llvm::InitializeNativeTargetAsmPrinter();
    llvm::InitializeNativeTargetAsmParser();

    prompt();

    llvm::llvm_shutdown();

    return 0;
}