

class Error(Exception):
    """
    Base class for exceptions in this module.
    """
    pass


class UpdaterError(Error):
    """
    Raised when an error occurs in the global updating process.
    """
    pass


class ParamError(Error):
    """
    Raised when a parameter is not correctly set.
    """
    pass


class DownloadError(UpdaterError):
    """
    Raised when a download operation
    """
    pass


class UpdateDatabaseError(UpdaterError):
    """
    Raised when an error occurs while trying to update the database.
    """
    pass
