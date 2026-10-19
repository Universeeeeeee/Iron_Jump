import unittest
from qtpy.QtCore import QCoreApplication,QObject,QThread,Signal,Slot,Qt,QEvent

class Sender(QObject):
    value=Signal(int)
    @Slot()
    def run(self):self.value.emit(7);QThread.currentThread().quit()

class Relay(QObject):
    value=Signal(int)
    @Slot(int)
    def receive(self,value):self.value.emit(value)

class Relays(unittest.TestCase):
    def test_posted_measurement_output_is_drained_after_thread_join(self):
        app=QCoreApplication.instance() or QCoreApplication([])
        values=[];thread=QThread();sender=Sender();relay=Relay();sender.moveToThread(thread)
        sender.value.connect(relay.receive,Qt.QueuedConnection);relay.value.connect(values.append)
        thread.started.connect(sender.run);thread.start();self.assertTrue(thread.wait(2000))
        self.assertEqual(values,[])
        QCoreApplication.sendPostedEvents(None,QEvent.MetaCall)
        self.assertEqual(values,[7])
