# Internal Archive implementation

This private module saves and loads supported Yosoi documents, captured
evidence, policies, and results on disk. It lets internal SDK operations
inspect or reuse previous work without fetching everything again. Archive
handles and storage types are not exported by the public `yosoi` facade.
