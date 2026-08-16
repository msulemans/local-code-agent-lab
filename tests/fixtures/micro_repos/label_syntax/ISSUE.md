# Label helper prevents the package from importing

After a small edit to the label formatter, importing the module fails before
any tests execute. Restore valid Python syntax while preserving the intended
trim-and-title behavior.
