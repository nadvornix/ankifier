
class SyncThread():

    # event = pyqtSignal(str, str)

    # def __init__(self, path, hkey, auth=None, media=True):
    #     QThread.__init__(self)
    #     self.path = path
    #     self.hkey = hkey
    #     self.auth = auth
    #     self.media = media
    #     self._abort = 0 # 1=flagged, 2=aborting

    def flagAbort(self):
        print ("FLAG ABORT")
        #self._abort = 1

    def run(self):
        # init this first so an early crash doesn't cause an error
        # in the main thread
        self.syncMsg = ""
        self.uname = ""
        try:
            self.col = Collection(self.path, log=True)
        except:
            self.fireEvent("corrupt")
            return
        self.server = RemoteServer(self.hkey)
        self.client = Syncer(self.col, self.server)
        self.sentTotal = 0
        self.recvTotal = 0
        def syncEvent(type):
            self.fireEvent("sync", type)
        def syncMsg(msg):
            self.fireEvent("syncMsg", msg)
        def sendEvent(bytes):
            if not self._abort:
                self.sentTotal += bytes
                self.fireEvent("send", str(self.sentTotal))
            elif self._abort == 1:
                self._abort = 2
                raise Exception("sync cancelled")
        def recvEvent(bytes):
            if not self._abort:
                self.recvTotal += bytes
                self.fireEvent("recv", str(self.recvTotal))
            elif self._abort == 1:
                self._abort = 2
                raise Exception("sync cancelled")
        addHook("sync", syncEvent)
        addHook("syncMsg", syncMsg)
        addHook("httpSend", sendEvent)
        addHook("httpRecv", recvEvent)
        # run sync and catch any errors
        try:
            self._sync()
        except:
            err = traceback.format_exc()
            self.fireEvent("error", err)
        finally:
            # don't bump mod time unless we explicitly save
            self.col.close(save=False)
            remHook("sync", syncEvent)
            remHook("syncMsg", syncMsg)
            remHook("httpSend", sendEvent)
            remHook("httpRecv", recvEvent)

    def _abortingSync(self):
        print("aborting sync")
        # try:
        #     return self.client.sync()
        # except Exception as e:
        #     if "sync cancelled" in str(e):
        #         self.server.abort()
        #         raise
        #     else:
        #         raise

    def _sync(self):
        if self.auth:
            # need to authenticate and obtain host key
            self.hkey = self.server.hostKey(*self.auth)
            if not self.hkey:
                # provided details were invalid
                return self.fireEvent("badAuth")
            else:
                # write new details and tell calling thread to save
                self.fireEvent("newKey", self.hkey)
        # run sync and check state
        try:
            ret = self._abortingSync()
        except Exception as e:
            log = traceback.format_exc()
            err = repr(str(e))
            if ("Unable to find the server" in err or
                "Errno 2" in err):
                self.fireEvent("offline")
            elif "sync cancelled" in err:
                pass
            else:
                if not err:
                    err = log
                self.fireEvent("error", err)
            return
        if ret == "badAuth":
            return self.fireEvent("badAuth")
        elif ret == "clockOff":
            return self.fireEvent("clockOff")
        elif ret == "basicCheckFailed" or ret == "sanityCheckFailed":
            return self.fireEvent("checkFailed")
        # full sync?
        if ret == "fullSync":
            return self._fullSync()
        # save and note success state
        if ret == "noChanges":
            self.fireEvent("noChanges")
        elif ret == "success":
            self.fireEvent("success")
        elif ret == "serverAbort":
            pass
        else:
            self.fireEvent("error", "Unknown sync return code.")
        self.syncMsg = self.client.syncMsg
        self.uname = self.client.uname
        # then move on to media sync
        self._syncMedia()

    def _fullSync(self):
        # tell the calling thread we need a decision on sync direction, and
        # wait for a reply
        print("_full sync")
        self.fullSyncChoice = False
        self.localIsEmpty = self.col.isEmpty()
        self.fireEvent("fullSync")
        while not self.fullSyncChoice:
            time.sleep(0.1)
        f = self.fullSyncChoice
        if f == "cancel":
            return
        self.client = FullSyncer(self.col, self.hkey, self.server.client)
        
        self.client.download()
        self.col.reopen()
        self._syncMedia()
        return

        self.fullSyncChoice = False
        self.localIsEmpty = self.col.isEmpty()
        self.fireEvent("fullSync")
        while not self.fullSyncChoice:
            time.sleep(0.1)
        f = self.fullSyncChoice
        if f == "cancel":
            return
        self.client = FullSyncer(self.col, self.hkey, self.server.client)
        try:
            if f == "upload":
                if not self.client.upload():
                    self.fireEvent("upbad")
            else:
                self.client.download()
        except Exception as e:
            if "sync cancelled" in str(e):
                return
            raise
        # reopen db and move on to media sync
        self.col.reopen()
        self._syncMedia()

    def _syncMedia(self):
        if not self.media:
            return
        self.server = RemoteMediaServer(self.col, self.hkey, self.server.client)
        self.client = MediaSyncer(self.col, self.server)
        try:
            ret = self.client.sync()
        except Exception as e:
            if "sync cancelled" in str(e):
                return
            raise
        if ret == "noChanges":
            self.fireEvent("noMediaChanges")
        elif ret == "sanityCheckFailed":
            self.fireEvent("mediaSanity")
        else:
            self.fireEvent("mediaSuccess")

    def fireEvent(self, cmd, arg=""):
        print("fire event "+cmd+args)

        # self.event.emit(cmd, arg)