from flask import Flask

class MyApp:
				app = Flask(__name__)
				app.config['PORT'] = 5000

				@app.route('/')
				def hello():
								return 'Hello, World!'

				def run(self):
								port = self.app.config['PORT']
								self.app.run(port=port)

if __name__ == '__main__':
				my_app = MyApp()
				my_app.run()